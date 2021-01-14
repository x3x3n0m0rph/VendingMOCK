from tkinter import *
import datetime
from threading import Timer
from PIL import Image, ImageTk
import pathlib
import math
import json
from collections import deque
import ctypes
import uuid
from paho.mqtt import client as mqtt_client

class Product:
    def __init__(self, id, name, price, count, image_pic):
        self.id = id
        self.name = name
        self.price = price
        self.count = count
        self.image = ImageTk.PhotoImage(file=image_pic)
        self._image = Image.open(image_pic)

class ProductLine:
    def __init__(self, height, width):
        self.height = height
        self.width = width
        self.count = 0
        self.productList = list()
        self.single_width = -1

    def add(self, product):
        self.productList.append(product)
        self.count += 1
        self.single_width = math.floor(self.width / self.count)

class LCDTextBox(Text):

    @property
    def value(self):
        return self.get(1.0, END)
    
    @value.setter
    def value(self, data):
        self.delete('1.0', END)
        self.insert(0.0, data)

class KeyboardButton(Button):
    def __init__(self, key, _handler, master=None, cnf={}, **kw):
        Button.__init__(self, master=None, cnf={}, **kw)
        self.bind('<Button-1>', lambda e, _key=key: _handler(e, _key))

class VendingView:

    displacement = list()
    enum = list()
    disp_labels = list()

    offsetX = 29
    offsetY = 29

    inputQueue = deque()
    outputQueue = deque()
    state = 0

    reservedStuffID = -1

    machineUUID = "machine000001"
    machineToken = "hhV62I7ETOAuQPGs8ftj"
    machineLocation = "улица Пушкина, дом Колотушкина"
    # mqtt_broker = 'demo.thingsboard.io'

    mqtt_iot_topic = "v1/devices/me/telemetry"
    mqtt_drop_topic = "vending/drop/" + machineUUID
    mqtt_instock_topic = "vending/instock/" + machineUUID 
    mqtt_request_instock_topic = "vending/request_instock"

    def __init__(self):
        self.root = Tk()
        self.root.title("Vending interface")
        self.root.geometry("600x697+100+100")
        self.root.overrideredirect(True)
        #self.paymentTimer = Timer(20.0, self.waitingState)
        self.path = pathlib.Path(__file__).parent.absolute().as_posix()

        # region background
        image_lblBackground = ImageTk.PhotoImage(file= self.path + "/img/background.png")
        lblBackground = Label(self.root, image = image_lblBackground)
        lblBackground.place(x=-2, y=-2)
        # endregion

        # region Close button
        photo_btnClose = ImageTk.PhotoImage(file = self.path + "/img/close.png")
        lblClose = Label(self.root, image=photo_btnClose)
        lblClose.place(x=600-photo_btnClose.width(), y=0)
        lblClose.bind('<Button-1>', self.btnCloseONCLICK)
        # endregion

        # region LCDText
        self.textLCD = LCDTextBox(width=20, height=2, bg="black", fg="lime")
        self.textLCD.place(x=425, y=65)
        self.waitingState()
        # endregion 

        # region keyboard

        captionsKeyboard = ('1','2','3','4','5','6','7','8','9','R','0',"OK")
        h = 0
        while h < 4:
            w = 0
            while w < 3:
                print(h*3+w)
                newButton = KeyboardButton(master=self.root, key=h*3+w+1, text = captionsKeyboard[h*3+w], width=2, height=1, _handler=self.KeyboardHandler)
                newButton.place(x=465+w*25, y=110+h*28)
                w +=1
            h += 1

        # endregion

        # region pickup button
        btnPickup = Button(self.root, text="Pick it up", width=13, height=1, cursor="@hand.cur", command=self.pickupStuff)
        btnPickup.place(x=450, y=500)
        # endregion

        # region pay label
        pth_lblTerminal = ImageTk.PhotoImage(file = self.path + "/img/terminal1.png")
        lblTerminal = Label(self.root, image=pth_lblTerminal, cursor="@card.cur")

        lblTerminal.place(x=342, y=150)
        lblTerminal.bind('<Button-1>', self.lblTerminalONCLICK)
        # endregion 

        # region machine ID
        lblmachineID = Label(self.root, text = "Machine: " + self.machineUUID)
        lblmachineID.place(x=425, y=10)
        # endregion 


        self.root.bind("<ButtonPress-1>", self.start_move)
        self.root.bind("<ButtonRelease-1>", self.stop_move)
        self.root.bind("<B1-Motion>", self.do_move)

        self.dispFromJSON(pathlib.Path(self.path + "/json.txt").read_text().replace('\n', ''))
        self.applyDisplacement()

        self.mqtt_iot = self.connect_mqtt(host = 'demo.thingsboard.io', username = self.machineToken)
        self.mqtt_drop = self.connect_mqtt(host = 'broker.hivemq.com')

        self.mqtt_drop.on_message = self.handleError
        self.subscribe(self.mqtt_drop, self.mqtt_drop_topic, self.remoteCommand)
        self.subscribe(self.mqtt_drop, self.mqtt_request_instock_topic, self.requestStock)
        
        self.root.attributes('-topmost', True)
        self.root.mainloop()

    def handleError(self, client, userdata, msg):
        print(msg.topic, ":", msg.payload.decode())

    def connect_mqtt(self, host, port = 1883, client_id = machineUUID, username = None, password = None):
        #print("Init MQTT client: " + host + "@" + str(port) + "" if username == None else (" user: " + username) + "" if password == None else ("@" + password))
        print("Init MQTT client:", host)
        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                print("Connected to MQTT Broker!")
            else:
                print("Failed to connect, return code ", rc)

        client = mqtt_client.Client(client_id)
        client.on_connect = on_connect
        client.username_pw_set(username, password)

        client.connect(host, port)
        client.loop_start()
        return client

    def publish(self, mqtt, payload, topic):
        result = mqtt.publish(topic, payload, qos=2)
        
        status = result[0]
        if status == 0:
            print(f"Send `{payload}` to topic `{topic}`")
        else:
            print(f"Failed to send message to topic {topic}")

    def subscribe(self, mqtt, topic, onmessage):
        
        mqtt.subscribe(topic)
        mqtt.message_callback_add(topic, onmessage)

        print("Subscribe for topic:", topic, "broker:", mqtt._host)

    def waitingState(self):
        self.printLCDText("CHOOSE STUFF")
        self.state = 0
        self.inputQueue.clear()
        self.applyDisplacement()

    def KeyboardHandler(self, event, key):
        #print(key)
        if self.state == 0:
            if key == 10: # R
                # clean last key
                if len(self.inputQueue) > 0:
                    self.inputQueue.pop()
                    stuffID = ""
                    i = 0
                    while i < len(self.inputQueue):
                        stuffID += str(self.inputQueue[i])
                        i += 1
                    self.printLCDText("CHOOSE STUFF", stuffID)
                

            elif key == 12: # OK
                # drop stuff
                if len(self.inputQueue) == 0: 
                    return

                stuffID = ""
                while self.inputQueue:
                    stuffID += str(self.inputQueue[0])
                    self.inputQueue.popleft()
                stuffID = int(stuffID)
                self.inputQueue.clear()

                if len(self.enum) <= stuffID:
                    # wrong stuff id
                    self.printLCDText("WROND ID")
                    self.state = 1
                    t = Timer(2.0, self.waitingState)
                    t.start()
                    
                else: 
                    # drop stuff
                    print("drop", stuffID)
                    self.dropStuffID(stuffID)

            else:
                if key == 11:
                    key = 0
                self.inputQueue.append(key)
                stuffID = ""
                i = 0
                while i < len(self.inputQueue):
                    stuffID += str(self.inputQueue[i])
                    i += 1
                self.printLCDText("CHOOSE STUFF", stuffID)
        if self.state == 2:
            if key == 10: # R
                self.waitingState()

    def printLCDText(self, str1="", str2=""):
        self.textLCD.value = str1.upper().ljust(20, ' ') + str2.upper().ljust(20, ' ')

    def dropStuffID(self, id):
        lineIndex = self.enum[id][0]
        productInLine = self.enum[id][1]
        #print(lineIndex,productInLine, self.displacement[lineIndex].productList[productInLine].name)
        #print(self.enum)
        if self.displacement[lineIndex].productList[productInLine].count > 0:

            self.printLCDText("PRICE: " + str(self.displacement[lineIndex].productList[productInLine].price), "STUFF: " + self.displacement[lineIndex].productList[productInLine].name)
            self.state = 2
            self.reservedStuffID = id
            #self.displacement[lineIndex].productList[productInLine].count -= 1
            self.paymentTimer = Timer(20.0, self.waitingState)
            self.paymentTimer.start()

        else:
            self.printLCDText("OUT OF STOCK")
            self.state = 1
            t = Timer(2.0, self.waitingState)
            t.start()

    def pickupStuff(self):
        self.outputQueue.clear()
        self.applyDisplacement()

    def dispFromJSON(self, jsonStr):

        self.displacement = list()

        jsonData = json.loads(jsonStr)
        for _line in jsonData["lines"]:
            newLine = ProductLine(_line["height"],_line["width"])
            for _prod in _line["products"]:
                newLine.add(Product(id = int(_prod["id"]),
                                    name = _prod["name"],
                                    price = float(_prod["price"]),
                                    count = int(_prod["count"]),
                                    image_pic = self.path + _prod["image"]
                ))
            self.displacement.append(newLine)

    def applyDisplacement(self):
        for lbl in self.disp_labels:
            lbl.destroy()
        self.disp_labels = list()
        self.enum = list()

        offsetY = self.offsetY
        internal_index = 0
        line = 0

        for _line in self.displacement:  
            product = 0
            offsetX = self.offsetX
            for _prod in _line.productList:
                
                
                if _prod.count > 0:
                    img = _prod._image.resize((_line.single_width,_line.height), Image.ANTIALIAS)
                else: 
                    img = Image.open(self.path + "/img/empty.png").resize((_line.single_width,_line.height), Image.ANTIALIAS)
                img = ImageTk.PhotoImage(img)

                lbl = Label(self.root, text=str(internal_index), borderwidth=1, relief="solid", image=img)
                lbl.image = img

                lblIndex = Label(lbl, text=str(internal_index),borderwidth=1, relief="solid")
                lbl.place(x=offsetX, y=offsetY)

                lblIndex.place(x=-1, y=-1)
                self.enum.append((line, product))

                self.disp_labels.append(lbl)
                self.disp_labels.append(lblIndex)

                internal_index += 1
                offsetX += _line.single_width
                product += 1
            line += 1
            offsetY += _line.height
        
        pickupOffsetX = 41
        pickupOffsetY = 598

        for _drop in list(self.outputQueue):
            img = _drop._image.resize((45,59), Image.ANTIALIAS)
            img = ImageTk.PhotoImage(img)

            lbl = Label(self.root,borderwidth=0, relief="solid", image=img)
            lbl.image = img
            lbl.place(x=pickupOffsetX, y=pickupOffsetY)
            self.disp_labels.append(lbl)

            pickupOffsetX += 45

    def btnCloseONCLICK(self, event = None):
        quit()

    def requestStock(self, client, userdata, msg):
        print("Remote request command")
        lines = list()
        for line in self.displacement:
            products = list()
            for product in line.productList:
                products.append({
                    "id": product.id,
                    "name": product.name,
                    "price": product.price,
                    "count": product.count,
                })
            lines.append({
                "height": line.height,
                "width": line.width,
                "products": products
            })
        machine = {
            "name": self.machineUUID,
            "addr": self.machineLocation,
            "lines": lines
        }
        self.publish(self.mqtt_drop, json.dumps(machine), self.mqtt_instock_topic)


    def remoteCommand(self, client, userdata, msg):
        print("Remote drop command")
        msg = json.loads(msg.payload.decode())

        lineIndex = self.enum[msg['drop']][0]
        productInLine = self.enum[msg['drop']][1]
        orderStatus = 1
        if self.displacement[lineIndex].productList[productInLine].count > 0:

            self.printLCDText("REMOTE COMMAND", "WAIT...")
            self.displacement[lineIndex].productList[productInLine].count -= 1
            self.outputQueue.append(self.displacement[lineIndex].productList[productInLine])

        else:
            self.printLCDText("OUT OF STOCK")
            self.state = 1
            orderStatus = 0


        objectJson = {
            "UUID": str(uuid.uuid4()),
            "orderDateTime": datetime.datetime.now().timestamp(),
            "orderStatus": orderStatus,
            "orderPrice": self.displacement[lineIndex].productList[productInLine].price,
            "orderItems": self.displacement[lineIndex].productList[productInLine].id,
            "orderPaymentMethod": "REMOTE"
        }

        self.publish(self.mqtt_iot, json.dumps(objectJson), self.mqtt_iot_topic)
        
        self.state = 1
        t = Timer(2.0, self.waitingState)
        t.start()

    def lblTerminalONCLICK(self, event = None):
        #withdraw from card
        # self.balance -= 
        if self.state != 2:
            return
        self.paymentTimer.cancel()

        lineIndex = self.enum[self.reservedStuffID][0]
        productInLine = self.enum[self.reservedStuffID][1]
        
        self.printLCDText("PAYMENT OK", "WAIT...")
        self.displacement[lineIndex].productList[productInLine].count -= 1
        self.outputQueue.append(self.displacement[lineIndex].productList[productInLine])

        objectJson = {
            "UUID": str(uuid.uuid4()),
            "orderDateTime": datetime.datetime.now().timestamp(),
            "orderStatus": 1,
            "orderPrice": self.displacement[lineIndex].productList[productInLine].price,
            "orderItems": self.displacement[lineIndex].productList[productInLine].id,
            "orderPaymentMethod": "MASTERCARD"
        }

        self.publish(self.mqtt_iot, json.dumps(objectJson), self.mqtt_iot_topic)

        self.state = 1
        t = Timer(2.0, self.waitingState)
        t.start()

    def start_move(self, event):
        self.x = event.x
        self.y = event.y

    def stop_move(self, event):
        self.x = None
        self.y = None

    def do_move(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")

    def alignCenter(self):
        windowWidth = self.root.winfo_reqwidth()
        windowHeight = self.root.winfo_reqheight()
        print("Width",windowWidth,"Height",windowHeight)
        positionRight = int(self.root.winfo_screenwidth()/2 - windowWidth/2)
        positionDown = int(self.root.winfo_screenheight()/2 - windowHeight/2)
        
        # Positions the window in the center of the page.
        self.root.geometry("+{}+{}".format(positionRight, positionDown))

if __name__ == "__main__":
    app = VendingView()