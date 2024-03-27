#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# https://github.com/clxjaguar/mk312-gui

VERSION = '0.11'
import sys, re, time, socket, serial, serial.tools.list_ports, fcntl

try:
	# sudo apt-get install python3-pyqt5
	from PyQt5.QtGui import *
	from PyQt5.QtCore import *
	from PyQt5.QtWidgets import *
	PYQT_VERSION = 5
	print("Using PyQt5")
except:
	# sudo apt-get install python-qtpy python3-qtpy
	try:
		from PyQt4.QtGui import *
		from PyQt4.QtCore import *
		PYQT_VERSION = 4
		print("Using PyQt4")
	except:
		sys.stderr.write("Error: PyQt seems to be missing!\n")
		sys.stderr.write("Please type: sudo apt install python3-qtpy\n")
		exit()

class BoxWorker(QObject):
	CLOSED = 0
	OPENING = 1
	CONNECTED = 2
	CLOSING = 3
	EXITING = -1

	modes = {0:   "None",   0x76:"Waves",  0x77:"Stroke",  0x78:"Climb",  0x79:"Combo",  0x7a:"Intense", 0x7b:"Rhythm",
	         0x7c:"Audio1", 0x7d:"Audio2",  0x7e:"Audio3", 0x7f:"Split",  0x80:"Random1", 0x81:"Random2", 0x82:"Toggle",
	         0x83:"Orgasm", 0x84:"Torment", 0x85:"Phase1", 0x86:"Phase2", 0x87:"Phase3",
	         0x88:"User1",  0x89:"User2",   0x8a:"User3",  0x8b:"User4",  0x8c:"User5",   0x8d:"User6",   0x8e:"User7"}

	powerlevels = {1:"Low (1)",2:"Normal (2)",3:"High (3)"}

	registers = {'advparam_ramp_level': 0x41f8, 'advparam_ramp_time': 0x41f9, 'advparam_depth': 0x41fa, 'advparam_tempo': 0x41fb,
	             'advparam_frequency': 0x41fc, 'advparam_effect': 0x41fd, 'advparam_width': 0x41fe, 'advparam_pace': 0x41ff,
	             'current_sense': 0x4060, 'multiadjust_value': 0x4061, 'multiadjust_scaled': 0x420d,
	             'multiadjust_min': 0x4086, 'multiadjust_max': 0x4087, 'psu_voltage': 0x4062,
	             'battery_voltage': 0x4063, 'battery_voltage_boot': 0x4203, 'channel_a_level': 0x4064,
	             'channel_b_level': 0x4065, 'power_level_range': 0x41f4,
	             'user_modes_loaded': {'addr': 0x41f3, 'offset': 0x87}, 'adc_disable': {'addr': 0x400f, 'bit': 0},
	             'box_version':0x00fc, 'v1':0x00fd, 'v2':0x00fe, 'v3':0x00ff, 'com_cipher_key':0x4213,
	             'current_mode': 0x407b, 'channel_a_split_mode': 0x41f5, 'channel_b_split_mode': 0x41f6, 'current_random_mode': 0x4074}

	boxNetworkAddressAutoDetected = pyqtSignal(str)
	commUpdated = pyqtSignal()
	statusUpdated = pyqtSignal(int, str)
	modeChanged = pyqtSignal(int)
	updatePowerRangeLevel = pyqtSignal(int)
	advancedParamsUpdated = pyqtSignal()
	potsOverrideUpdated = pyqtSignal(bool)

	def __init__(self):
		QObject.__init__(self)
		self.box = None
		self.state = self.CLOSED
		self.portName = None
		self.socatRedirector = None

		self.thread = QThread()
		self.thread.setObjectName("BoxWorker thread")
		self.moveToThread(self.thread)
		self.thread.started.connect(self.worker)
		self.thread.start()

	def open(self, portName):
		self.portName = portName

	def close(self):
		self.portName = None

	def stop(self):
		self.state = self.EXITING
		self.portName = None

	def getVal(self, name):
		if name not in self.paramsValues:
			return float('nan')
		return self.paramsValues[name]

	def setVal(self, name, value):
		if name not in self.registers:
			self.statusUpdated.emit(2, name+" unknown!")
		else:
			self.registersToWrite[name] = value

	def discover(self, timeout=0.5):
		UDP_DISCOVERY_PORT = 8842
		message = b"ICQ-MK312"

		hosts = set()
		server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
		server.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
		server.settimeout(timeout)
		server.sendto(message, ('255.255.255.255', UDP_DISCOVERY_PORT))
		t = time.time()

		try:
			while(True):
				data, addr = server.recvfrom(1024)
				elapsed_ms = 1000 * (time.time() - t)
				print("%f.2 (%.2fms) %s: %s (%s)" % (time.time(), elapsed_ms, addr[0], data, '.'.join(map(str, data))))
				if addr[1] == UDP_DISCOVERY_PORT:
					hosts.add(addr[0])

		except socket.timeout:
			pass

		except Exception as e:
			raise(e)
			print(str(e))

		return hosts

	def worker(self):
		print("Starting BoxWorker.worker()")
		self.paramsValues = {}
		self.registersToWrite = {}
		self.errorCounter = 0

		while(self.state != self.EXITING):
			if self.state == self.CLOSED:
				if self.portName != None:
					self.state = self.OPENING
					continue
				else:
					for addr in self.discover():
						self.boxNetworkAddressAutoDetected.emit(addr)
				time.sleep(0.5)

			elif self.state == self.CLOSING:
				try:
					self.writeRegistersToBox()
					self.box.close()
					self.state = self.CLOSED
					self.statusUpdated.emit(1, "Port closed.")
				except Exception as e:
					self.statusUpdated.emit(3, str(e))

			elif self.state == self.OPENING:
				if self.portName == None:
					self.statusUpdated.emit(1, "Aborting etablishing connection...")
					self.state = self.CLOSED
					continue

				self.registersToWrite = {}
				try:
					if re.search('^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$', self.portName):
					    self.box = MK312(NetworkLink(self.portName, port=8843), encrypted=False)
					else:
					    self.box = MK312(SerialLink(self.portName))
					self.state = self.CONNECTED
					self.errorCounter = 0

					self.storeParamValue("battery_voltage_boot")

					v = self.storeParamValue("power_level_range")
					self.updatePowerRangeLevel.emit(v)

					usermodes = self.storeParamValue("user_modes_loaded")
					for i in range (0,usermodes):
						startmodule = self.box.peek(0x8018+i)
						if (startmodule < 0xa0):
							programlookup = self.box.peek(0x8000+startmodule-0x60)
							programblockstart = 0x8040+programlookup
						else:
							programlookup = self.box.peek(0x8000+startmodule-0xa0)
							programblockstart = 0x8100+programlookup
						print("\tUser %d is module 0x%02x\t: 0x%04x (eeprom)"%(i+1,startmodule,programblockstart))

					self.storeParamValue("box_version")
					self.storeParamValue("v1")
					self.storeParamValue("v2")
					self.storeParamValue("v3")
					self.potsOverrideUpdated.emit(self.storeParamValue('adc_disable'))


					self.storeParamValue('advparam_ramp_level')
					self.storeParamValue('advparam_ramp_time')
					self.storeParamValue('advparam_depth')
					self.storeParamValue('advparam_tempo')
					self.storeParamValue('advparam_frequency')
					self.storeParamValue('advparam_effect')
					self.storeParamValue('advparam_width')
					self.storeParamValue('advparam_pace')
					self.advancedParamsUpdated.emit()

					self.statusUpdated.emit(1, "Connected and synchronised!")
					lastMode = None

				except Exception as e:
					self.errorCounter+=1
					msg = str(e)
					if self.errorCounter < 4:
						self.statusUpdated.emit(2, msg)
					else:
						msg+="\nCannot synchronise with mk312... "
						if "received no reply" in msg:
							msg+="Is the box connected and powered on?"
						else:
							msg+="Try to turn off the box and on again?"
						self.statusUpdated.emit(3, msg)
					time.sleep(.2)

			elif self.state == self.CONNECTED:
				if self.portName == None:
					self.state = self.CLOSING
					continue

				try:
					self.writeRegistersToBox()

					# ~ self.storeParamValue("current_sense") # ADC0
					self.storeParamValue("multiadjust_scaled")

					currentmode = self.storeParamValue("current_mode")
					if currentmode != lastMode:
						self.storeParamValue("multiadjust_min")
						self.storeParamValue("multiadjust_max")

						self.modeChanged.emit(currentmode)
						lastMode = currentmode

						v = self.storeParamValue("power_level_range")
						self.updatePowerRangeLevel.emit(v)


						if (currentmode == 0x7f):
							self.storeParamValue("channel_a_split_mode")
							self.storeParamValue("channel_b_split_mode")
						if (currentmode == 0x80):
							self.storeParamValue("current_random_mode")
							# ~ timeleft = self.box.peek(0x4075) - self.box.peek(0x406a)
							# ~ if (timeleft<0):
								# ~ timeleft+=256
							# ~ print("\tTime until change mode\t: {0:#d} seconds ".format(int(timeleft/1.91)))
						# ~ print("\tMode has been running\t: {0:#d} seconds".format(int((self.box.peek(0x4089)+self.box.peek(0x408a)*256)*1.048)))


					self.storeParamValue("psu_voltage") # ADC2
					self.storeParamValue("battery_voltage") # ADC3

					self.storeParamValue("channel_a_level") # ADC4
					self.storeParamValue("channel_b_level") # ADC5


					self.commUpdated.emit()

					# ~ self.storeParamValue('advparam_ramp_level')
					# ~ self.storeParamValue('advparam_ramp_time')
					# ~ self.storeParamValue('advparam_depth')
					# ~ self.storeParamValue('advparam_tempo')
					# ~ self.storeParamValue('advparam_frequency')
					# ~ self.storeParamValue('advparam_effect')
					# ~ self.storeParamValue('advparam_width')
					# ~ self.storeParamValue('advparam_pace')
					# ~ self.advancedParamsUpdated.emit()

					self.errorCounter = 0
				except Exception as e:
					self.errorCounter+=1
					self.statusUpdated.emit(3, str(e))
					if self.errorCounter % 5 == 0:
						try:
							 # important or the MK312 object is not deleted
							self.box.close()
							self.box = None
						except Exceptiona as e:
							print(str(e))
						self.state = self.OPENING

		try:
			# if possible, reset the key and close the interface
			self.box.close()
		except:
			pass
		print("BoxWorker ended")

	def storeParamValue(self, name):
		if type(self.registers[name]) == dict:
			register = self.registers[name]['addr']
			if 'bit' in self.registers[name]:
				value = self.box.peek(register) & (1 << self.registers[name]['bit'])

			elif 'offset' in self.registers[name]:
				offset = self.registers[name]['offset']
				value = self.box.peek(register) - offset
		else:
			register = self.registers[name]
			value = self.box.peek(register)

		self.paramsValues[name] = value
		return value

	def overWriteDisplay(self, text, posOffset=None):
		""" overwrite name of current mode with spaces, then display text on it """
		self.box.poke(0x4180, [0x64])
		self.box.poke(0x4070, [0x15])
		while (self.box.peek(0x4070) != 0xff):
			pass

		if not posOffset:
			posOffset = 9 if len(text) < 8 else 8

		for pos, char in enumerate(text):
			self.box.poke(0x4180, [ord(char), pos+posOffset])
			self.box.poke(0x4070, [0x13])
			i = 0
			while (self.box.peek(0x4070) != 0xff and i < 50):
				i+=1

	def writeRegistersToBox(self):
		for i, name in enumerate(self.registersToWrite.copy()):
			if type(self.registers[name]) == dict:
				addr = self.registers[name]['addr']
				if 'bit' in self.registers[name]:
					bit = self.registers[name]['bit']
					value = self.box.peek(addr)
					value&= ~(1 << bit)
					if self.registersToWrite[name]:
						value|= 1 << bit
				else:
					value = self.registersToWrite[name]
			else:
				addr = self.registers[name]
				value = self.registersToWrite[name]

			print(name, addr, value)
			if name == 'current_mode' and self.modes[value] == "None":
				value = 0x90
				# so let's get it into a blank empty mode. easiest way is calltable 18
				self.box.poke(0x4078, [0x90]) # mode 90 doesn't exist
				self.box.poke(0x4070, [18]) # execute mode 90
				i = 0
				while (self.box.peek(0x4070) != 0xff and i < 50):
					i+=1
				for base in [0x4000,0x4100]:
					# init
					self.box.poke(base+0xa8, [0,0]) # don't increment channel intensity
					self.box.poke(base+0xa5, [128]) # A intensity mod value = min
					self.box.poke(base+0xac, [0]) # no select
					self.box.poke(base+0xb1, [0]) # rate
					self.box.poke(base+0xae, [0x64]) # freq mod
					self.box.poke(base+0xb5, [4]) # select normal parms
					self.box.poke(base+0xb7, [0xc8]) # width mod value
					self.box.poke(base+0xba, [0]) # width mod value
					self.box.poke(base+0xbe, [4]) # select normal parms
					self.box.poke(base+0x9c, [255]) # ramp off

					# actuated
					# ~ self.box.poke(base+0xac, [0]) # no select
				self.overWriteDisplay("None")
				del self.registersToWrite[name]
				continue

			self.box.poke(addr, [value])

			if name == 'current_mode':
				self.box.poke(0x4070, [0x4, 0x12])
				time.sleep(0.018)
			elif name.startswith("advparam_"):
				self.box.poke(0x4070, [0x20])
				time.sleep(0.018)

			del self.registersToWrite[name]
			if i > 3:
				break


class MK312():
	def __init__(self, link, encrypted=True):
		self.link = link                   # the Communication layer to the device
		self.encryptionEnabled = encrypted # do we use the Encryptionless method or not

		self._flushInputBuffer()
		self._handshake()
		self._negotiateKeys()

	def _flushInputBuffer(self):
		attempts = 0
		while (True):
			s = self.link.recv(1024)
			if not s:
				break
			attempts+=1
			print("Flushed:", s)
			if attempts > 5:
				s = str(s)
				if len(s) > 20:
					s = s[:20] + '...'
				raise Exception("Device doesn't stop sending bytes (%s)" % (s))

	def _handshake(self):
		""" Attempts the handshake with the MK312 device """
		attempts = 0
		ok = 0
		while (True):
			self.link.send(bytes([0x00])) # Send a 0 as a hello
			time.sleep(0.1)
			reply = self.link.recv(1)
			if (len(reply) == 1 and reply[0] == 0x07):
				ok+=1
				if ok > 2:
					break
				continue
			ok=0
			attempts+=1
			if (attempts > 12): raise Exception("Handshake with device failed")

	def _negotiateKeys(self):
		""" Do the key handshake with the device """

		# this encryptionless mode is only supported by RexLabs Wifi adapter
		# (https://github.com/Rangarig/MK312WIFI/)
		if (not self.encryptionEnabled):
			self.link.send(bytes((0x2f, 0x42, 0x42)))
			rx = self.link.recv(100)
			if len(rx) != 1 or rx[0] != 0x69: raise Exception("Failed to establish non encrypted mode")
			return

		# Send key negotiation
		# code is working only if it is set to zero, but does not seems to break the connection
		hostKey = 0x00          # The key sent by us, 0 for simplicity
		extraEncryptKey = 0x55  # The key always added to the encryption
		while True:
			self.link.send(bytes((0x2f, hostKey, 0x2f)))
			data = self._read(3) # this does the checksum validation
			if len(data) == 2:
				break

		boxkey = data[1]
		self.encryptionKey = (boxkey ^ hostKey ^ extraEncryptKey)

	def _write(self, data):
		checksum = sum(data) % 256
		data.append(checksum)

		if self.encryptionEnabled:
			data = [x ^ self.encryptionKey for x in data]
		self.link.send(bytes(data))

	def _read(self, length):
		start = time.time()
		data = self.link.recv(length)
		while len(data) < length and time.time() < start + 0.5:
			data+= self.link.recv(length-len(data))

		if len(data) < 2:
			raise Exception("Read data too short! %d < 2" % (len(data)))

		data, checksum = data[:-1], data[-1]
		computedChecksum = sum(data) % 256
		if computedChecksum != checksum:
			raise Exception("Checksum mismatch! (%02x != %02x)" % (computedChecksum, checksum))
		return data

	def peek(self, address):
		self._write([0x3c, address >> 8, address & 0xff])
		data = self._read(3)
		return data[1]

	def poke(self, startAddress, data):
		if not self.link: return

		if type(data) is not list:
			raise TypeError("data must be a list")
		length = len(data)
		if length == 0 or length > 8:
			raise Exception("Can only write between 1-8 bytes")

		txData = [0x0d | ((length+3) << 4), startAddress >> 8, startAddress & 0xff] + data
		txData.append(sum(txData) % 256)

		if not self.encryptionEnabled:
			self.link.send(bytes(txData))
		else:
			self.link.send(bytes([b ^ self.encryptionKey for b in txData]))

		ackCode = self.link.recv(1)
		return ackCode

	def close(self):
		if self.encryptionEnabled:
			self.poke(0x4213, [0x0]) # reset key
		self.link = None


class NetworkLink():
	def __init__(self, ip, port, debug=False):
		self.debug = debug
		self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.socket.settimeout(0.1)
		self.socket.connect((ip, port))

	def send(self, data):
		if self.debug: print("send", data.hex())
		self.socket.send(data)

	def recv(self, length=1):
		try:
			data = self.socket.recv(length)
			if self.debug: print("recv %s (%d/%d)" % (data.hex(), len(data), length))
			return data
		except TimeoutError:
			if self.debug: print("recv (nothing) (0/%d)" % (length))
			return b""


class SerialLink():
	def __init__(self, port, baudrate=19200, debug=False):
		self.debug = debug
		if self.debug: print("opening serial port", port)
		self.serial = serial.Serial(port, baudrate, timeout=0.2, parity=serial.PARITY_NONE, bytesize=8, stopbits=1, xonxoff=0, rtscts=0)
		fcntl.flock(self.serial.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

	def send(self, data):
		if self.debug: print("send", data.hex())
		self.serial.write(data)

	def recv(self, length=1):
		data = self.serial.read(length)
		if self.debug: print("recv %s (%d/%d)" % (data.hex(), len(data), length))
		return data

	def __del__(self):
		if self.debug: print("serial port closed.")
		self.serial.close()
		del self.serial


boxWorker = BoxWorker()

class RegistersView(QTableWidget):
	closed = pyqtSignal()

	def __init__(self):
		QWidget.__init__(self)
		self.initUI()

	def closeEvent(self, event):
		self.closed.emit()
		event.accept()

	def initUI(self):
		self.setStyleSheet('QLabel { background: white; }')
		self.verticalHeader().setDefaultSectionSize(self.verticalHeader().minimumSectionSize())
		self.verticalHeader().hide()
		self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
		self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
		self.setColumnCount(2)
		self.setHorizontalHeaderLabels(("Name", "Value"))
		self.setColumnWidth(0, 200)
		self.setColumnWidth(1, 80)
		# ~ self.setStretchLastSection(True)

		self.setWindowTitle(u"Box Registers")
		self.refresh()
		w = self.verticalHeader().width() + self.horizontalHeader().length() + self.frameWidth()*2 + self.verticalScrollBar().sizeHint().width()
		self.setMinimumWidth(w)
		self.resize(w, 600)

		self.show()
		self.timer = QTimer()
		self.timer.timeout.connect(self.refresh)
		self.timer.start(1000)

	def refresh(self):
		# ~ parameters = {'battery_voltage_boot': 210, 'power_level_range': 2, 'user_modes_loaded': 0, 'box_version': 167, 'v1': 169, 'v2': 255, 'v3': 35, 'adc_disable': 0, 'advparam_ramp_level': 225, 'advparam_ramp_time': 20, 'advparam_depth': 215, 'advparam_tempo': 1, 'advparam_frequency': 25, 'advparam_effect': 5, 'advparam_width': 130, 'advparam_pace': 5, 'multiadjust_scaled': 229, 'current_mode': 141, 'multiadjust_min': 15, 'multiadjust_max': 255, 'psu_voltage': 125, 'battery_voltage': 165, 'channel_a_level': 0, 'channel_b_level': 0}

		parameters = boxWorker.paramsValues.copy()
		# ~ print(parameters)
		if len(parameters) != self.rowCount():
			self.setRowCount(len(parameters))
			for i, parameterName in enumerate(parameters):

				keyLabel = QLabel(parameterName)
				valueLabel = QLabel(str(parameters[parameterName]))
				valueLabel.setAlignment(Qt.AlignRight|Qt.AlignVCenter)

				for label in (keyLabel, valueLabel):
					label.setTextInteractionFlags(Qt.TextBrowserInteraction)

				keyLabel.setStyleSheet('padding-left: 3px;')
				valueLabel.setStyleSheet('padding-right: 3px;')

				self.setCellWidget(i, 0, keyLabel)
				self.setCellWidget(i, 1, valueLabel)

		else:
			for i, parameterName in enumerate(parameters):
				self.cellWidget(i, 1).setText(str(parameters[parameterName]))


class GUI(QWidget):
	def __init__(self):
		QWidget.__init__(self)

		boxWorker.statusUpdated.connect(self.boxStatusUpdated)
		boxWorker.commUpdated.connect(self.boxCommUpdated)
		boxWorker.modeChanged.connect(self.updateMode)
		boxWorker.updatePowerRangeLevel.connect(self.updatePowerRangeLevel)
		self.initUI()
		boxWorker.boxNetworkAddressAutoDetected.connect(self.serialPortPicker.addPort)
		boxWorker.advancedParamsUpdated.connect(self.advParameters.paramsUpdate)
		boxWorker.potsOverrideUpdated.connect(lambda state: self.potsOverrideClicked(state))

		try:
			self.udpServer = UDP_ServerWorker(port=50000)
			self.udpServer.receivedPacket.connect(self.handleUDPMessage)
		except Exception as e:
			QMessageBox.warning(self, "UDP REMote control port error", str(e))
			for ch in self.channels:
				ch.setUdpServerIsHavingProblem(True)

	def handleUDPMessage(self, msg):
		factor = 0
		try:
			if msg != '':
				factor = float(msg)
		except Exception as e:
			print(str(e))

		self.channels[0].setRemoteValueFactor(factor)
		self.channels[1].setRemoteValueFactor(factor)

	def closeEvent(self, event):
		boxWorker.close()
		if self.registersView:
			self.registersView.close()
		event.accept()

	def initUI(self):
		self.setStyleSheet("\
			QLabel#value { font-size: 24pt; } \
			QProgressBar#channel { font-size: 24px; background-color: transparent; border: 0px solid black; text-align: center; margin-bottom: 8px; } \
			QProgressBar::chunk#channel { background-color: QLinearGradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #000000ff, stop: 1 #ff0000ff ); } \
			QLabel#label { font-size: 12pt; } \
			QPushButton::checked#green { color: #000000; background: #00ff00; } \
			QPushButton::checked#normal { color: #000000; background: #70ff70; } \
			QPushButton::pressed#surge { color: #000000; background: #ff0000; } \
			QPushButton::checked#surge { color: #000000; background: #ff0000; } \
			QPushButton::checked#cut { color: #808080; background: #000000; } \
			QPushButton::checked#remote { color: #000000; background: #1070ff; } \
			QSplitter::handle:vertical   { image: none; } \
			QSplitter::handle:horizontal { width:  2px; image: none; } \
			QGroupBox { border: 1px solid #707070; border-radius: 6px; padding: 0px; } \
		");
		self.setObjectName("backgroundWidget")
		layout = QVBoxLayout(self)
		def closeFct():
			for ch in self.channels[0], self.channels[1]:
				ch.computeValue(0)
				ch.clear()
			boxWorker.close()
		self.serialPortPicker = SerialPortPicker(self, boxWorker.open, closeFct)
		layout.addLayout(self.serialPortPicker)

		def mkQLabel(text=None, layout=None, alignment=Qt.AlignLeft, objectName=None):
			o = QLabel()
			if objectName:
				o.setObjectName(objectName)
			o.setAlignment(alignment)
			if text:
				o.setText(text)
			if layout != None:
				layout.addWidget(o)
			return o

		def mkButton(text, layout=None, function=None, gridPlacement=(0,0), gridSpan=(1,1), setCheckable=False, toolButton=False, objectName=None, enabled=True):
			if not toolButton:
				btn = QPushButton(text)
			else:
				btn = QToolButton()
				btn.setText(text)
			btn.setCheckable(setCheckable)
			if objectName:
				btn.setObjectName(objectName)
			btn.setFocusPolicy(Qt.TabFocus)
			if function:
				btn.clicked.connect(function)
			if not enabled:
				btn.setEnabled(False)
			if type(layout) == QGridLayout:
				layout.addWidget(btn, gridPlacement[0], gridPlacement[1], gridSpan[0], gridSpan[1])
			elif layout != None:
				layout.addWidget(btn)
			return btn

		self.errorLabel = mkQLabel(" ", layout, Qt.AlignLeft | Qt.AlignTop)
		self.errorLabel.hide()
		self.errorLabel.setWordWrap(True)
		self.errorLabelHideTimer = QTimer()
		self.errorLabelHideTimer.timeout.connect(self.hideErrorLabelTimerTimeout)

		layout.addStretch()

		self.infos = mkQLabel("", layout)

		channelsLayout = QHBoxLayout()
		layout.addLayout(channelsLayout)

		class ChannelWidget(QGroupBox):
			def __init__(self, channelName, writeRegisterName):
				QGroupBox.__init__(self)

				self.value = float('nan')
				self.isDefaultPosition = True
				self.writeRegisterName = writeRegisterName
				self.remServerNotWorking = False
				self.remoteControlFactor = 0.0

				channelsLayout.addWidget(self)
				layout = QVBoxLayout(self)
				layout.setSpacing(0)

				self.levelBar = QProgressBar()
				self.levelBar.setRange(0, 255)
				self.levelBar.setObjectName('channel')
				self.levelBar.setFormat("")
				layout.addWidget(self.levelBar)

				layout2 = QHBoxLayout()
				layout2.setSpacing(0)
				layout.addLayout(layout2)
				layout3 = QVBoxLayout()
				layout3.setSpacing(0)
				layout2.addLayout(layout3)
				self.dial = QDial()
				self.dial.valueChanged.connect(self.dialValueChanged)
				self.dial.setNotchTarget(26)
				self.dial.setNotchesVisible(True)
				self.dial.setRange(0, 255)
				self.dial.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
				layout3.addWidget(self.dial)

				layout4 = QVBoxLayout()
				layout4.setSpacing(0)
				layout2.addWidget(QLabel())
				layout2.addLayout(layout4)

				def mkBtn(s, f, l, n=None, checkable=False, checked=False):
					b = QPushButton()
					b.setText(s)
					if checkable or checked:
						b.setCheckable(True)
						b.clicked.connect(f)
					else:
						b.isPressed=False
						def fct():
							b.isPressed=True
							f()
						b.pressed.connect(fct)

						def fct():
							b.isPressed=False
							f()
						b.released.connect(fct)

					if checked:
						b.setChecked(True)
					if n:
						b.setObjectName(n)
					b.setEnabled(False)

					l.addWidget(b)
					return b

				self.btnSurge  = mkBtn("+10%!", self.dialValueChanged, layout4, 'surge')
				self.btnNorm   = mkBtn("NRM", lambda s: self.buttonClicked(self.btnNorm, s), layout4, 'normal', checkable=True)
				self.btnRemote = mkBtn("REM", lambda s: self.buttonClicked(self.btnRemote, s), layout4, 'remote', checkable=True)
				self.btnCut    = mkBtn("CUT", lambda s: self.buttonClicked(self.btnCut, s), layout4, 'cut', checkable=True)
				self.lastCheckedButton = self.btnCut
				mkQLabel(channelName, layout3, Qt.AlignCenter | Qt.AlignTop, 'label')
				self.setEnabled(False)

			def setUdpServerIsHavingProblem(self, state):
				self.remServerNotWorking = state

			def buttonClicked(self, btn=None, state=None):
				if state:
					for b in self.btnSurge, self.btnNorm, self.btnRemote, self.btnCut:
						if b != btn and b.isChecked():
							b.setChecked(False)
							self.lastCheckedButton = b
				else:
					self.lastCheckedButton.setChecked(True)
					self.lastCheckedButton = btn

				self.dialValueChanged()

			def setRemoteValueFactor(self, factor):
				self.remoteControlFactor = float(factor)
				if self.remoteControlFactor < 0:
					self.remoteControlFactor = 0
				elif self.remoteControlFactor > 2:
					self.remoteControlFactor = 2

				if self.btnRemote.isChecked():
					self.dialValueChanged()

			def update(self, value): #todo: change that name
				self.value = value
				if not self.enabled or self.isDefaultPosition:
					self.dial.setValue(value)
					self.isDefaultPosition = False
				if not self.enabled:
					self.levelBar.setValue(self.value)
				self.levelBar.setFormat("%02d" % (self.value / 2.56))

			def clear(self):
				self.levelBar.setValue(0)
				self.levelBar.setFormat("")

			def dialValueChanged(self): #todo: change that name
				value = self.dial.value()
				self.computeValue(value)

			def computeValue(self, value):
				if self.btnRemote.isChecked():
					value*=self.remoteControlFactor
				if self.btnSurge.isPressed:
					value+=25.5
				if self.btnCut.isChecked():
					value = 0
				if self.enabled:
					if type(value) != int: value = int(round(value))
					if   value < 0:        value = 0
					elif value > 255:      value = 255
					self.levelBar.setValue(value)
					boxWorker.setVal(self.writeRegisterName, value)
					if value > 0:
						self.levelBar.setStyleSheet("QProgressBar::chunk#channel { background-color: QLinearGradient(x1: 0, y1: 0, x2: %f, y2: 0, stop: 0 #000000ff, stop: 1 #ff0000ff ); border-radius: 5px; }" % (255/value));

			def setEnabled(self, state):
				self.dial.setEnabled(state)
				for b in self.btnSurge, self.btnNorm, self.btnRemote, self.btnCut:
					b.blockSignals(True)
					b.setEnabled(state)
					if not state:
						b.setChecked(False)
					b.blockSignals(False)
				if state:
					if not self.enabled:
						self.btnNorm.setChecked(True)
						self.lastCheckedButton = self.btnCut

				if self.remServerNotWorking:
					self.btnRemote.setEnabled(False)

				self.enabled = state

		class MultiAdjustWidget(QGroupBox):
			def __init__(self, writeRegisterName):
				QGroupBox.__init__(self)
				channelsLayout.addWidget(self)
				layout = QVBoxLayout(self)
				layout.setSpacing(0)
				self.valueLabel = mkQLabel("--", layout, Qt.AlignCenter | Qt.AlignTop, 'value')
				self.dial = QDial()
				self.dial.setNotchTarget(9)
				self.dial.setNotchesVisible(True)
				self.setEnabled(False)
				self.dial.setRange(0, 255)
				self.dial.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
				self.valMin, self.valMax = 0, 255
				self.dial.valueChanged.connect(self.dialValueChanged)
				layout.addWidget(self.dial)
				mkQLabel("Multi Adj.", layout, Qt.AlignCenter | Qt.AlignTop, 'label')
				self.value = float('nan')
				self.isDefaultPosition = True
				self.writeRegisterName = writeRegisterName

			def update(self, value, valMin, valMax):
				self.valueLabel.setText("%d" % (value))
				self.valMin, self.valMax = valMin, valMax
				self.dial.setRange(0, valMax - valMin)
				if not self.enabled or self.isDefaultPosition:
					self.dial.setValue(valMax - value)
					self.isDefaultPosition = False

			def dialValueChanged(self, value):
				if self.enabled:
					boxWorker.setVal(self.writeRegisterName, (self.valMax - value))

			def setEnabled(self, state):
				self.enabled = state
				self.dial.setEnabled(state)

		class AdvancedParameters(QGroupBox):
			def __init__(self):
				QGroupBox.__init__(self)
				channelsLayout.addWidget(self)
				layout = QGridLayout(self)
				layout.setSpacing(0)
				self.sliders = {}
				# ~ self.setSizeHint()

				for i, p in enumerate([("Ramp Level", 'advparam_ramp_level', 50, 100, 70),
				                       ("Ramp Time", 'advparam_ramp_time', 1, 120, 20),
				                       ("Depth", 'advparam_depth', 10, 100, 60),
				                       ("Tempo", 'advparam_tempo', 1, 100, 1),
				                       ("Frequency", 'advparam_frequency', 15, 250, 150),
				                       ("Effect", 'advparam_effect', 1, 100, 5),
				                       ("Width", 'advparam_width', 70, 250, 130),
				                       ("Pace", 'advparam_pace', 1, 100, 5)]):

					labelName, paramName, mini, maxi, default = p
					slider = QSlider(Qt.Horizontal)
					slider.paramName = paramName
					if paramName == 'advparam_ramp_level':
						slider.granularity = 10; slider.paramOffset = 155
					else:
						slider.granularity = 1;  slider.paramOffset = 0

					slider.setMinimumWidth(150)
					slider.setRange(int(mini/slider.granularity), int(maxi/slider.granularity))
					slider.setValue(int(default/slider.granularity))
					slider.valueChanged.connect(self.valueChanged)
					slider.valueLabel = QLabel(str(slider.value()*slider.granularity))
					layout.addWidget(QLabel(labelName), i, 0)
					layout.addWidget(slider, i, 2)
					layout.addWidget(slider.valueLabel, i, 3)
					self.sliders[paramName] = slider


			def valueChanged(self, i):
				# ~ print(self.sender().paramName, i, self.sender().valueLabel)
				i*=self.sender().granularity
				self.sender().valueLabel.setText("%d" % i)
				boxWorker.setVal(self.sender().paramName, i+self.sender().paramOffset)


			def paramsUpdate(self):
				for paramName in self.sliders:
					slider = self.sliders[paramName]
					value = boxWorker.getVal(paramName) - slider.paramOffset
					slider.blockSignals(True)
					slider.valueLabel.setText("%d" % value)
					slider.setValue(int(value / slider.granularity))
					slider.blockSignals(False)

		self.channels = (ChannelWidget("A Level", 'channel_a_level'), ChannelWidget("B Level", 'channel_b_level'))
		self.multiAdjust = MultiAdjustWidget('multiadjust_scaled')
		self.advParameters = AdvancedParameters()

		layout2 = QHBoxLayout()

		self.potsOverrideBtn = mkButton("Override Pots", layout2, function=self.potsOverrideClicked, setCheckable=True)

		def showRegistersBtnClicked(state):
			if state:
				self.registersView = RegistersView()
				self.registersView.closed.connect(lambda: self.showRegistersBtn.setChecked(False))
			elif self.registersView != None:
				self.registersView.close()
				self.registersView = None

		self.showRegistersBtn = mkButton("Show Registers", layout2, function=showRegistersBtnClicked, setCheckable=True)
		self.registersView = None

		layout2.addStretch()

		layout2.addStretch()

		mkQLabel("Mode", layout2, Qt.AlignCenter)
		self.mode = QComboBox()
		self.mode.insertItems(0, ['None'])
		self.mode.currentTextChanged.connect(self.modeChanged)
		layout2.addWidget(self.mode)
		self.fillModes()
		layout2.addStretch()

		mkQLabel("Power Level", layout2, Qt.AlignCenter)
		self.powerRangeLevel = QComboBox()
		self.powerRangeLevel.insertItems(0, boxWorker.powerlevels.values())
		self.powerRangeLevel.currentTextChanged.connect(self.powerRangeLevelChanged)
		layout2.addWidget(self.powerRangeLevel)

		self.batteryBar = QProgressBar()
		layout2.addWidget(self.batteryBar)

		layout.addLayout(layout2)

		self.setWindowTitle(u"MK-312 Remote Control v%s" % (VERSION))
		self.setWindowIcon(getEmbeddedIcon())
		self.show()

	def boxStatusUpdated(self, level, text):
		self.errorLabel.show()
		self.errorLabel.setText(text)
		if level == 2:
			color = '#ffff77'
		elif level == 3:
			color = '#ff7777'
		else:
			color = 'none'
		self.errorLabel.setStyleSheet("background-color: "+color+"; border: 1px solid #707070;")

		if level <= 1: # This had been added. Unsure about this.
			self.errorLabelHideTimer.start(2000)
		else:
			self.errorLabelHideTimer.stop()
		print(time.strftime("%Y-%m-%d %H:%M:%S")+" " + text)

	def hideErrorLabelTimerTimeout(self):
		self.errorLabelHideTimer.stop()
		self.errorLabel.setText("")
		self.errorLabel.hide()
		self.errorLabel.setStyleSheet("background-color: none;")

	def boxCommUpdated(self):
		# ~ print(boxWorker.paramsValues)
		self.channels[0].update(boxWorker.getVal('channel_a_level'))
		self.channels[1].update(boxWorker.getVal('channel_b_level'))
		self.multiAdjust.update(boxWorker.getVal('multiadjust_scaled'), boxWorker.getVal('multiadjust_min'), boxWorker.getVal('multiadjust_max'))

		batteryVoltage = float(boxWorker.getVal('battery_voltage')) / 12.425
		psuVoltage = boxWorker.getVal('psu_voltage') * 0.12
		# ~ infos = ""
		# ~ infos+="%s: %.0f%%\n" % ('Battery at boot', boxWorker.getVal('battery_voltage_boot') / 2.56)
		# ~ infos+="%s: %.4fV\n" % ('Battery', batteryVoltage)
		# ~ infos+="%s: %.4fV\n" % ('PSU', psuVoltage)
		# ~ infos+="%s: %d"   % ('current_sense', boxWorker.getVal('current_sense'))

		self.batteryBar.setFormat("%.1fV" % round(batteryVoltage, 1))
		batteryBarValue = int((batteryVoltage - 11.5) * 57.14)
		if batteryBarValue > 100: batteryBarValue = 100
		elif batteryBarValue < 0: batteryBarValue = 0
		self.batteryBar.setValue(batteryBarValue)

	def potsOverrideClicked(self, state):
		#state = self.potsOverrideBtn.isChecked()
		boxWorker.setVal('adc_disable', state)
		for w in self.channels[0], self.channels[1], self.multiAdjust:
			w.setEnabled(state)
		self.potsOverrideBtn.setChecked(state)

	def fillModes(self):
		self.mode.blockSignals(True)
		self.mode.clear()
		modesText = []
		self.modeNames2Id = {}
		for k in boxWorker.modes:
			modesText.append(boxWorker.modes[k])
			self.modeNames2Id[boxWorker.modes[k]] = k
		self.mode.insertItems(0, modesText)
		self.mode.blockSignals(False)

	def updateMode(self, modeId):
		self.mode.blockSignals(True)
		try:
			text = boxWorker.modes[modeId]
			self.mode.setCurrentText(text)
		except KeyError:
			print("Unknown mode:", modeId)

		self.mode.blockSignals(False)

	def modeChanged(self, modeName):
		modeId = self.modeNames2Id[modeName]
		print("mode:", modeName, modeId)
		boxWorker.setVal('current_mode', modeId)

	def updatePowerRangeLevel(self, rangeLevel):
		self.powerRangeLevel.blockSignals(True)
		try:
		    text = boxWorker.powerlevels[rangeLevel]
		    self.powerRangeLevel.setCurrentText(text)
		    print("updatePowerRangeLevel", rangeLevel, text)
		except KeyError:
			print("Unknown range level:", rangeLevel)

		self.powerRangeLevel.blockSignals(False)

	def powerRangeLevelChanged(self, levelText):
		for k, v in boxWorker.powerlevels.items():
			if v == levelText:
				levelId = k

		print("powerRangeLevel:", levelText, levelId)
		boxWorker.setVal('power_level_range', levelId)

class SerialPortPicker(QHBoxLayout):
	def __init__(self, parentWidget, portOpenFunction=None, portCloseFunction=None):
		QHBoxLayout.__init__(self)
		self.portOpenFunction = portOpenFunction
		self.portCloseFunction = portCloseFunction
		self.parentWidget = parentWidget

		self.refreshBtn = QToolButton()
		self.refreshBtn.setText(u"↻")
		self.refreshBtn.clicked.connect(self.refreshSerial)
		self.addWidget(self.refreshBtn)

		self.serialDeviceCombo = QComboBox()
		self.serialDeviceCombo.setEditable(True)
		self.serialDeviceCombo.currentTextChanged.connect(self.serialDeviceChanged)
		self.addWidget(self.serialDeviceCombo)

		self.openBtn = QPushButton("Open")
		self.openBtn.setDisabled(True)
		self.openBtn.clicked.connect(self.openPortClicked)
		self.addWidget(self.openBtn)
		self.closeBtn = QPushButton("Close")
		self.closeBtn.clicked.connect(self.closePortClicked)
		self.closeBtn.setDisabled(True)
		self.addWidget(self.closeBtn)
		self.refreshSerial()

	def serialDeviceChanged(self, text):
		self.openBtn.setDisabled(False if text.strip() != "" else True)

	def listSerialPorts(self):
		result = []
		for port in serial.tools.list_ports.comports():
			result.append(tuple(port)[0])
		return result

	def refreshSerial(self):
		try:
			self.serialDeviceCombo.clear()
			self.serialDeviceCombo.insertItems(0, self.listSerialPorts())
			self.serialDeviceCombo.insertSeparator(self.serialDeviceCombo.count())
			self.serialDeviceCombo.setCurrentIndex(-1)
		except Exception as e:
			QMessageBox.warning(self.parentWidget, "Serial port error", str(e))

	def addPort(self, portName):
		if portName not in [self.serialDeviceCombo.itemText(i) for i in range(self.serialDeviceCombo.count())]:
			self.serialDeviceCombo.addItem(portName)
			self.serialDeviceCombo.setCurrentIndex(self.serialDeviceCombo.count()-1)

	def openPortClicked(self):
		try:
			portName = self.serialDeviceCombo.currentText()
			self.portOpenFunction(portName)

			self.refreshBtn.setDisabled(True)
			self.serialDeviceCombo.setDisabled(True)
			self.closeBtn.setDisabled(False)
			self.openBtn.setDisabled(True)

		except Exception as e:
			QMessageBox.warning(self.parentWidget, "Serial port error", str(e))

	def closePortClicked(self):
		self.portCloseFunction()

		self.refreshBtn.setDisabled(False)
		self.serialDeviceCombo.setDisabled(False)
		self.openBtn.setDisabled(False)
		self.closeBtn.setDisabled(True)


class UDP_ServerWorker(QObject):
	receivedPacket = pyqtSignal(str)

	def __init__(self, port=50000):
		QObject.__init__(self)
		self.port = port
		self.receive_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
		self.receive_socket.bind(('', self.port))
		self.serverThread = QThread()
		self.serverThread.setObjectName("UDP Server Thread")
		self.moveToThread(self.serverThread)
		self.serverThread.started.connect(self.run)
		self.serverThread.start()

	def run(self):
		self.exitLoop = False

		while not self.exitLoop:
			msg, addr = self.receive_socket.recvfrom(4096)
			try:
				for content in msg.decode('ascii').strip().split("\n"):
					self.receivedPacket.emit(content)

			except Exception as e:
				print('UDP ERROR: '+str(e))


	def stop(self):
		self.exitLoop = True

def main():
	app = QApplication(sys.argv)
	m1 = GUI()
	app.installEventFilter(m1)
	ret = app.exec_()
	boxWorker.stop()
	time.sleep(1)
	sys.exit(ret)

def getEmbeddedIcon():
	qpm = QPixmap()
	icon = QIcon()
	qba_s = QByteArray(bytes(ICON.encode()))
	qba = QByteArray.fromBase64(qba_s)
	qpm.convertFromImage(QImage.fromData(qba.data(), 'PNG'))
	icon.addPixmap(qpm)
	return icon

ICON = "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"

if __name__ == '__main__':
	main()
