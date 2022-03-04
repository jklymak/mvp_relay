"""
mvp_relay--Relays incoming navigation data on multiple serial and/or
UDP ports to MVP controller computer via a single UDP port.

Navigation data includes depthsounder information. The depthsounder on
the Tully transmits a depth of zero whenever it cannot find the
bottom. This causes problems because the MVP controller aborts the
profile if it sees too shallow a depth. The mvp_relay program avfoids
this problem by withholding zero depths from the MVP controller.

The MVP controller also aborts the profile if too long a time has
passed with no depth values arriving. There is no alarm raised, so
there is the possibility that the operator will not notice that data
acquisition has stopped for some time. The mvp_relay program pops up a
warning dialogue after a user-defined timeout period to alert the
operator that the profile may have been aborted.

The program also logs the relayed data.

Kevin Bartlett, 2009-01-08 14:03 PST.

Based on a program by Jacob Hallen, AB Strakt, Sweden, found at
http://code.activestate.com/recipes/82965/.

"""

from Tkinter import *
import time
import threading
import Queue
import serial
import socket
import math

################################################################
# These constants can be changed to alter program behaviour:

# Socket parameters for relaying data to MVP controller:
#mvpControllerIP = "142.104.154.118"
mvpControllerIP = "192.168.1.200"
#mvpControllerIP = "192.168.2.160"

# ...MVP controller should be set to listen on this port for
# UDP datagrams.
udpOutPort = 2021

# Port numbers for receiving data via UDP datagram. Echosounder, etc.,
# should be set to send data on these ports. udpInPorts is a list
# variable, with port numbers separated by commas. Can contain zero,
# one or more port numbers.
#udpInPorts = []
#udpInPorts = [21567, 21568]
#udpInPorts = [21567]
udpInPorts = [23]
print 'hello'

# Additional UDP parameters:
udpInBufferLength = 1024 # [bytes]
UDPTIMEOUT = 1 # [seconds]

# TCP parameters:
tcpInPorts = [50008]
tcpAddresses = ['127.0.0.1']
tcpInBufferLength = 1024

# Port numbers for receiving data via serial port. serialInPorts is a
# list variable identifying serial ports. For portability between
# operating systems, it is supposed to be best to use integer 1, 2,
# etc. (0 fails), but I have found these don't work on my Linux
# box. Under Linux, then, you may have to use strings containing port
# NAMES (e.g., '/dev/ttyS1'). A USB/serial adapter may result in
# serial ports named '/dev/ttyUSB0', etc. (check /var/log/messages).
serialInPorts = []
#serialInPorts = [12]
#serialInPorts = [1,2,3]
#serialInPorts = ['/dev/ttyS1','/dev/ttyS2']
#serialInPorts = ['/dev/ttyUSB0','/dev/ttyUSB1','/dev/ttyUSB2']
#serialInPorts = ['/dev/ttyUSB0']


# Additional serial parameters:

# ...Baud rate
baudRate=4800

# ...Number of data bits.
byteSize = serial.EIGHTBITS

# ...Enable parity checking.
parity = serial.PARITY_NONE

# ...Number of stopbits.
stopBits = serial.STOPBITS_ONE

# ...Timeout of None means read() waits forever.
timeOut = 1 # [seconds]

# ...Want flow control to be "None", so disable other
# flow controls:

# ......Disable software flow control.
xonxoff = 0

# ......Disable RTS/CTS flow control.
rtscts = 0

# ...Inter-character timeout. "None" disables.
interCharTimeout = None

# Number of seconds of no depth data or only zero depths before
# operator is warned. This default value can be overridden in
# GUI.
#DEFAULTDEPTHTIMEOUT = 3000000
DEFAULTDEPTHTIMEOUT = 20000000

# New log files will be created after a certain amount of time has
# passed.
MINUTES_PER_LOG = 60;

# Give user time to react; don't pop up no-depth-data warnings 
# more often than this many seconds:
TIMEBETWEENWARNINGS = 600

# Apparent bug in tkinter causes lift() to fail to raise warning dialogue
# to top of window stack. Workaround by "refreshing" dialogue box
# periodically.
WD_REFRESHINTERVALSECONDS = 2

# GUI appearance:
windowWidth = 400
windowHeight = 600
dataTextHeight = 12 # (text windows height in lines of text)

# ...Number of rows of serial and UDP data to store for
# display. If too small compared to dataTextHeight, there
# will be blank space in display.
NUMTEXTROWS = 14

# Calculate checksums of NMEA strings. Will only relay datagrams
# to MVP controller if they are valid strings with the correct
# checksum. Set this constant to False if the navigation datagrams
# have no checksums appended to them (in NMEA strings, the checksum
# is a 2-character hex number following an asterisk). If set to
# True and there are no checksums, then NO datagrams will be sent
# to the MVP controller).
USECHECKSUMS = FALSE

################################################################
class FIFOTextStack:

    """    
    Manage a FIFO stack of text lines. The FIFO stack controls what is
    passed to the GUI for display.        
    """

    #****************
    def __init__(self,numRows):
        self.numRows = numRows
        self.textList = []

        # Map ASCII control characters (0-31) and non-ASCII characters
        # (129-255) to question marks for display in GUI.
        #self.asciiCharTable = "".join(map(chr,range(128))) + "?"*128
        #self.asciiCharTable = "?"*256
        self.asciiCharTable = "?"*32 + "".join(map(chr,range(32,128))) + "?"*128

    #****************
    def push(self,newTextLine):
        # Pushes a new line onto the end of the stack. If stack
        # exceeds specified length, then the first line of the
        # stack is discarded.

        # Convert any ASCII control characters and non-ASCII characters to 
        # question marks before putting them on the stack.
        newTextLine = newTextLine.translate(self.asciiCharTable)
        self.textList.append(newTextLine)

        if len(self.textList) > self.numRows:
            self.textList = self.textList[1:]

    #****************
    def outputString(self):
        # Outputs multi-line string, suitable for use in Tk Label object.
        outStr = ''
        iLine = 0

        for thisLine in self.textList:
            outStr = outStr + thisLine
            iLine = iLine + 1

            # Add newline character (except for last line).
            if iLine < self.numRows:
                outStr = outStr + '\n'

        return outStr          

################################################################
class GuiPart:
    def __init__(self, master, serialQueue, udpQueue, endCommand):

        self.lastDepthEpochTime = time.time()
        self.lastDepthCloseTime = time.time()
        self.secondsSinceLastDepth = 0
        self.depthTimeOutSeconds = DEFAULTDEPTHTIMEOUT

        self.serialQueue = serialQueue
        self.udpQueue = udpQueue

        # Make FIFO text stack to contain lines of UDP data.
        self.udpTextStack = FIFOTextStack(NUMTEXTROWS)

        # Make FIFO text stack to contain lines of serial data.
        self.serialTextStack = FIFOTextStack(NUMTEXTROWS)

        # Set up the GUI
        #console = Tkinter.Button(master, text='Done', command=endCommand)
        #console.pack()
        # Add more GUI stuff here
        master.geometry(str(windowWidth) + 'x' + str(windowHeight))
        master.title("MVP Relay")

        # Make container for controls.
        controlContainer = Frame(master,bg='gray',borderwidth=5,pady=20)      
        controlContainer.pack(side=BOTTOM,fill=BOTH,expand=1)
        self.controlContainer = controlContainer

        # Make text-entry control.
        depthTimeOutSecondsEntry = Entry(controlContainer,width=3)

        depthTimeOutSecondsEntry.bind('<Return>', \
           (lambda event: \
           self.depthTimeOutSecondsEntryCallback(depthTimeOutSecondsEntry)))

        depthTimeOutSecondsEntry.delete(0, END)
        depthTimeOutSecondsEntry.insert(0,self.depthTimeOutSeconds)
        depthTimeOutSecondsEntry.pack(side=RIGHT,fill=NONE,expand=1,anchor=W)
        self.depthTimeOutSecondsEntry = depthTimeOutSecondsEntry

        # Make title for text-entry control.
        ToEntryTitleLabel = Label(controlContainer,\
                                  bg='gray',
                                  text="Depth timeout [seconds]:   ")
        ToEntryTitleLabel.pack(side=RIGHT,fill=NONE,expand=1,anchor=E)

        # Make container for UDP data.
        udpContainer = Frame(master,bg='gray',borderwidth=0,\
                             padx=20,pady=10)
        udpContainer.configure(relief=FLAT)
        udpContainer.pack(side=TOP,expand=YES,fill=BOTH)

        # Label object to use as title for UDP data:
        udpTitleLabel = Label(udpContainer,text="UDP Data",\
                            width=windowWidth,bg='gray')
        udpTitleLabel.pack(side=TOP,pady=5)

        # Label object to hold UDP data.
        udpLabel = Label(udpContainer,text="",\
                            width=windowWidth,\
                            borderwidth=5,\
                            relief=SUNKEN,\
                            height=dataTextHeight)

        udpLabel.configure(justify=LEFT,anchor=SW)
        udpLabel.pack(side=TOP,ipady=10)
        self.udpLabel = udpLabel

        # Make container for serial data.
        serialContainer = Frame(master,bg='gray',borderwidth=0,\
                                padx=20,pady=10)
        serialContainer.configure(relief=FLAT)
        serialContainer.pack(side=TOP,expand=YES,fill=BOTH)

        # Label object to use as title for Serial data:
        serialTitleLabel = Label(serialContainer,text="Serial Data",\
                            width=windowWidth,bg='gray')
        serialTitleLabel.pack(side=TOP,pady=5)

        # Label object to hold serial data.
        serialLabel = Label(serialContainer,text="",\
                            width=windowWidth,\
                            borderwidth=5,\
                            relief=SUNKEN,\
                            height=dataTextHeight)

        serialLabel.configure(justify=LEFT,anchor=SW)
        serialLabel.pack(side=TOP,ipady=10)
        self.serialLabel = serialLabel
        self.serialLabel.configure(text='')

        # Make a depth warning dialogue box.
        depthWarningWindow = DepthWarningWindow(self)
        depthWarningWindow.resizable(width=FALSE,height=FALSE)
        depthWarningWindow.withdraw()
        
    def processIncoming(self):
        """
        Handle all the messages currently in the queue (if any).
        """ 
        #global lastDepthEpochTime
        #global lastDepthCloseTime

        # Warn user if no depth datagrams have been sent in the specified
        # timeout period.

        # ..Determine number of seconds since last depth was relayed.
        self.secondsSinceLastDepth = time.time() - self.lastDepthEpochTime
        
        if self.secondsSinceLastDepth >= self.depthTimeOutSeconds: 
            
            # It has been more than depthTimeOutSeconds since the last
            # depth was relayed to the MVP controller. Warn the operator.
            #self.depthWarningWindow.showDepthWarning()    
            secondsSinceLastWarningClosed = time.time() - self.lastDepthCloseTime

            if secondsSinceLastWarningClosed > TIMEBETWEENWARNINGS:
                self.depthWarningWindow.showDepthWarning()    

        serialQueueSize = self.serialQueue.qsize()
        udpQueueSize = self.udpQueue.qsize()

        while serialQueueSize > 0 or udpQueueSize > 0:
            serialQueueSize = self.serialQueue.qsize()
            udpQueueSize = self.udpQueue.qsize()

            getFailed = False
            
            try:
                msg = self.serialQueue.get(0)
            except:
                # Was "except Queue.Empty", but want to catch any error, not
                # just Queue.Empty.
                getFailed = True
                
            if getFailed == False:
                # Log the message without modification, apart from adding
                # a timestamp.
                datedMsg = time.strftime("%Y-%m-%d %H:%M:%S",time.localtime()) + '--' + msg
                datedMsg = datedMsg.rstrip()
                logMessage(datedMsg) 
                self.serialTextStack.push(datedMsg)                
                outputStr = self.serialTextStack.outputString()
                self.serialLabel.configure(text=outputStr)

                # Relay the message if it is of correct format or if it can be
                # converted to the correct format with minimal tweaking.
                
                msg,isGoodStr = clean_nmea_str(msg)
                if isGoodStr:
                    relayMessage(msg,self)                    

            getFailed = False

            try:
                msg = self.udpQueue.get(0)
            except:
                # Was "except Queue.Empty", but want to catch any error, not
                # just Queue.Empty.
                getFailed = True

            if getFailed == False:
                # Log the message without modification, apart from adding
                # a timestamp.
                datedMsg = time.strftime("%Y-%m-%d %H:%M:%S",time.localtime()) + '--' + msg
                datedMsg = datedMsg.rstrip()
                logMessage(datedMsg) 
                self.udpTextStack.push(datedMsg)                
                outputStr = self.udpTextStack.outputString()
                self.udpLabel.configure(text=outputStr)

                # Relay the message if it is of correct format or if it can be
                # converted to the correct format with minimal tweaking.
                #print 'boo' + msg
                msg,isGoodStr = clean_nmea_str(msg)
                #print 'boo' + msg
                
                #isGoodStr = nmea_checksum(msg)

                # Relay the message if it is of correct format.
                if isGoodStr:
                    relayMessage(msg,self)
                    
    def depthTimeOutSecondsEntryCallback(self,depthTimeOutSecondsEntry):
        # Callback for abort threshold entry box.
        #global depthTimeOutSeconds
        depthTimeOutSecondsStr = depthTimeOutSecondsEntry.get()

        # Try to convert string in entry box to a number to see if
        # it is a valid entry.
        try:
            newDepthTimeOutSeconds = float(depthTimeOutSecondsStr)
        except:
            # Revert to previous timeout value.
            newDepthTimeOutSeconds = self.depthTimeOutSeconds

        # Convert to integer (decimal values are rounded off).
        if math.isinf(newDepthTimeOutSeconds):
            if newDepthTimeOutSeconds > 0:
                newDepthTimeOutSeconds = float('inf')
            else:
                newDepthTimeOutSeconds = float('-inf')
        else:
            newDepthTimeOutSeconds = int(round(newDepthTimeOutSeconds))

        # Revert to previous timeout value if a negative or zero value
        #  was entered.
        if newDepthTimeOutSeconds <= 0:
            newDepthTimeOutSeconds = self.depthTimeOutSeconds

        self.depthTimeOutSeconds = newDepthTimeOutSeconds

        depthTimeOutSecondsEntry.delete(0, END)
        depthTimeOutSecondsEntry.insert(0,self.depthTimeOutSeconds)        

        # Change warning label in depth timeout dialogue window to match
        # new timeout value.
        self.setWarningLabel()

        # Make warning dialogue invisible if time since last depth is less
        # than new timeout value.
        if self.secondsSinceLastDepth < self.depthTimeOutSeconds:        
            self.depthWarningWindow.withdraw()

    def setWarningLabel(self):
        # Sets the warning label in the depth timeout warning dialogue.        
        warnStr = 'The stream of depth values relayed \n to the MVP controller ' + \
                  'was interrupted for more than ' + str(self.depthTimeOutSeconds) + ' seconds.\n' + \
            ' The MVP profile may have been aborted. \n\n' + \
            'Set depth timeout to "inf" to disable this warning.'  
        self.depthWarningWindow.warnLabel.configure(text=warnStr)


class DepthWarningWindow(Toplevel):

    #****************
    def __init__(self, myParent):
        Toplevel.__init__(self)
        self.title("MVP Relay Warning")
        self.parent = myParent
        self.protocol("WM_DELETE_WINDOW",self.zdWarnCloseCallback)

        WARNINGFRAMEPAD = 5

        # Make container for warning text.
        warnContainer = Frame(self,bg='red',padx=WARNINGFRAMEPAD,pady=WARNINGFRAMEPAD)
        warnContainer.pack(side=TOP)

        # Make container for "okay" button.
        buttonContainer = Frame(self,bg='red',padx=WARNINGFRAMEPAD,pady=WARNINGFRAMEPAD)
        buttonContainer.pack(side=TOP,fill=BOTH)

        warnLabel = Label(warnContainer,text='',bg='red')
        self.warnLabel = warnLabel

        # Make DepthWarningWindow instance an attribute of the main window. This
        # should probably be done elsewhere, but I can't quite figure out how.
        myParent.depthWarningWindow = self

        myParent.setWarningLabel()
        warnLabel.pack(side=TOP)
        self.warnLabel = warnLabel

        # Insert "okay" button.
        OKbutton = Button(buttonContainer, text="OK", \
                          command=self.zdWarnCloseCallback,pady=4,anchor=CENTER)
        OKbutton.pack(side=TOP,fill=NONE,expand=0)

        self.wd_timeLastRefreshed = float('-inf')

    def showDepthWarning(self):
        # Makes depth warning window visible.
        ###########################################################
        #self.iconify()
        self.update()
        self.deiconify()
        self.lift(aboveThis=root)
        secondsSinceLastRefresh = time.time() - self.wd_timeLastRefreshed

        # Apparent bug in tkinter causes lift() to fail to raise
        # warning dialogue to top of window stack. Workaround by
        # "refreshing" dialogue box periodically.
        if secondsSinceLastRefresh > WD_REFRESHINTERVALSECONDS:
            self.bell()
            self.withdraw()
            self.deiconify()

            # Even this workaround doesn't quite work. Use an 
            # iconify/deiconify to at least make the display
            # flicker. This is messy, but there seems no other
            # way.
            self.iconify()
            self.deiconify()
            self.lift()
            self.wd_timeLastRefreshed = time.time()

    def zdWarnCloseCallback(self):
        # User has acknowledged gap in depth data, so reset time variable
        # to start counting seconds from now.
        self.lastDepthEpochTime = time.time()

        # If depth timeout is set to a low value like 1 second, it may be
        # difficult for user to change its value in the main window before
        # the depth warning dialogue takes focus again. Avoid this by
        # not allowing dialogue to pop up immediately after being closed.
        self.parent.lastDepthCloseTime = time.time()
        self.withdraw()

class ThreadedClient:
    """
    Launch the main part of the GUI and the worker thread. periodicCall and
    endApplication could reside in the GUI part, but putting them here
    means that you have all the thread controls in a single place.
    """
    def __init__(self, master):
        """
        Start the GUI and the asynchronous threads. We are in the main
        (original) thread of the application, which will later be used by
        the GUI. We spawn a new thread for the worker.
        """
        self.master = master

        # Create the queues.
        self.serialQueue = Queue.Queue()
        self.udpQueue = Queue.Queue()

        # Set up the GUI part
        self.gui = GuiPart(master, self.serialQueue, self.udpQueue, self.endApplication)

        self.running = 1

        # Start thread(s) for relaying serial data to MVP controller.
        self.serialRelayThreads = {} # (dictionary variable)

        for serialInPort in serialInPorts:
            self.serialRelayThreads[serialInPort] = \
                threading.Thread(target=self.serialThread, args=(serialInPort,))
            self.serialRelayThreads[serialInPort].start()

        # Start thread(s) for relaying UDP data to MVP controller.
        self.udpRelayThreads = {} # (dictionary variable)

        for udpInPort in udpInPorts:
            self.udpRelayThreads[udpInPort] = \
                threading.Thread(target=self.udpThread, args=(udpInPort,))
            self.udpRelayThreads[udpInPort].start()

        # Start the periodic call in the GUI to check if the queue contains
        # anything
        self.periodicCall()

    def periodicCall(self):
        """
        Check every 100 ms if there is something new in the queue.
        """
        self.gui.processIncoming()

        if not self.running:

            # Wait for serial thread(s) to complete.
            for serialInPort in self.serialRelayThreads.keys():
                self.serialRelayThreads[serialInPort].join()
            
            # Wait for UDP thread(s) to complete.
            for udpInPort in self.udpRelayThreads.keys():
                self.udpRelayThreads[udpInPort].join()
            
            import sys
            sys.exit(1)
            
        self.master.after(200, self.periodicCall)

    def serialThread(self,serialInPort):
        #print 'serialInPort is ' + str(serialInPort)

        # Open serial port.
        try:
            self.ser = serial.Serial(serialInPort,baudRate,\
                                    bytesize=byteSize,parity=parity,\
                                    stopbits=stopBits,timeout=timeOut,\
                                    xonxoff=xonxoff,rtscts=rtscts,\
                                    interCharTimeout=interCharTimeout)
        except:
            print 'Failed to open serial port'

        while self.running:

            # Read in data from network.
            serialData = ''

            try:
                serialData = self.ser.readline()
                print serialData
            except:
                pass

            # If serial connection timed out, then serialData will be empty.
            if len(serialData) > 0:
                self.serialQueue.put(serialData)

        # Close incoming serial connection.
        try:
            self.ser.close()
        except:
            pass

    def udpThread(self,udpInPort):
        print 'udpInPort is ' + str(udpInPort)

        # Create socket for listening to incoming UDP data.
        relayIP = '' # (Symbolic name meaning the local host)
        relayAddr = (relayIP,udpInPort)
        print relayAddr
        inUdpSocket = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        inUdpSocket = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        inUdpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        inUdpSocket.settimeout(UDPTIMEOUT)
        # ...Bind incoming UDP socket to address of local machine.
        inUdpSocket.bind(relayAddr)

        while self.running:
            # Read in data from network.
            udpData = ''

            try:
                udpData = inUdpSocket.recv(udpInBufferLength)
            except:
                pass

            # If UDP connection timed out, then udpData will be empty.
            if len(udpData) > 0:

                # udpData is not empty; echo datagram to GUI.
                self.udpQueue.put(udpData)

        # Close incoming UDP socket.        
        try:
            inUdpSocket.close()
        except:
            pass


    def endApplication(self):
        self.running = 0


def logMessage(msg):

    global logFid, timeLastLogStarted

    # Create new log file if necessary.

    # ...Check if time to create new log file.
    secondsSinceLastNewLog = time.time() - timeLastLogStarted

    if secondsSinceLastNewLog > MINUTES_PER_LOG*60:
        # Close existing log file.
        if logFid != 0:
            logFid.close()

        # Log files will have names with start times encoded
        # in them (e.g., 'mvp_relay_20081015164302.log').
        nowStr = time.strftime("%Y%m%d%H%M%S",time.localtime())
        newLogName = 'mvp_relay_' + nowStr + '.log'
        logFid = open(newLogName,'w')
        timeLastLogStarted = time.time()

    msg = msg + '\n'
    logFid.write(msg)
    logFid.flush()

def relayMessage(msg,gui):

    # Determine if this is a depth datagram or not.
    fields = msg.split(',')
    nmeaID = fields[0]

    #print nmeaID
    if nmeaID == "$FKDBS":
        print msg
    if nmeaID == "$SDDBS" or nmeaID == "$SDDPT" or nmeaID =='$PKEL9':
        isDepthDataGram = 1
    else:
        isDepthDataGram = 0
    #print msg
    #print nmeaID
    #print fields[1]
    if len(msg) == 0:
        # Do not send empty datagrams.
        pass
    elif isDepthDataGram == 0:

        # Datagram is not a depth datagram.
        try:
#            print msg
            #outUdpSocket.sendto(msg.strip(),mvpAddr)
            outUdpSocket.sendto(msg.strip()+'\n',mvpAddr)
        except:
            print 'Send of non-depth datagram to controller computer failed'

    elif nmeaID == "$PKEL9":
        depthStr = fields[5]
        depth = float(depthStr)
        #print depth
        print msg
        if depth != 0:
            # Depth value is not zero, so it will be relayed to
            # MVP controller. Record the time of this event.
            gui.lastDepthEpochTime = time.time()

            # Relay message to MVP controller.
            try:
                outUdpSocket.sendto(msg,mvpAddr)
            except:
                print 'Send of $SDDBS datagram to controller computer failed'

        
    elif nmeaID == "$SDDBS":

        # Datagram is a depth datagram of "$SDDBS" format. This is the
        # format output by the Tully's Simrad ER60 multi-frequency
        # echosounder (we usually use the 18-kHz channel). The ER60
        # outputs a zero-depth datagram whenever it cannot find the
        # bottom, which causes the MVP controller to abort the cast,
        # believing the water depth to be too shallow. Avoid this
        # problem by checking that the datagram does not contain a
        # zero depth before relaying it to the MVP controller.

        # ...Determine depth from echosounder message.
        depthStr = fields[3]
        depth = float(depthStr)

        if depth != 0:
            # Depth value is not zero, so it will be relayed to
            # MVP controller. Record the time of this event.
            gui.lastDepthEpochTime = time.time()

            # Relay message to MVP controller.
            try:
                outUdpSocket.sendto(msg,mvpAddr)
            except:
                print 'Send of $SDDBS datagram to controller computer failed'

    elif nmeaID == "$FKDBS":

        # ...Determine depth from echosounder message.
        depthStr = fields[4]
        depth = float(depthStr)
        print depth

        if depth != 0:
            # Depth value is not zero, so it will be relayed to
            # MVP controller. Record the time of this event.
            gui.lastDepthEpochTime = time.time()

            # Relay message to MVP controller.
            try:
                outUdpSocket.sendto(msg,mvpAddr)
            except:
                print 'Send of $FKDBS datagram to controller computer failed'
    else:

        # Datagram is a depth datagram, but of $SDDPT format. This is
        # the type of NMEA string that comes from the EA600
        # Kongsburg-Simrad single-frequency sounder on the Tully (the
        # EA600 is supposed to be able to output other formats, but
        # the software is apparently buggy, and it will only output
        # $SDDPT datagrams). It is not clear from the MVP manual that
        # a $SDDPT datagram will be understood by the MVP software,
        # but it must, since according to Jody Klymak, they used the
        # EA600 on the Station P cruise for a while.

        # Also according to Jody Klymak, the EA600 had the same problem
        # with zero depths being sent to the MVP controller, causing
        # profiles to be aborted. Not sure if the MVP software is using
        # the depth below the transducer or the true depth, so test for
        # zeroes in both.
        depthStr = fields[1]
        offsetStr = fields[2]
        depthBelowT = float(depthStr)
        depthBelowS = depthBelowT + float(offsetStr)

        # ...Relay message to MVP controller.
        msg = msg.strip() + '\n'
        #outUdpSocket.sendto(msg,mvpAddr)
        #gui.lastDepthEpochTime = time.time()

        if depthBelowT != 0 and depthBelowS != 0:
            try:
                outUdpSocket.sendto(msg,mvpAddr)
                gui.lastDepthEpochTime = time.time()
            except:
                print 'Send of $SDDPT depth datagram to controller computer failed'
        else:
            print 'zero depth withheld'

def clean_nmea_str(nmeaStr):
    # Checks that datagram is of correct NMEA format or can be converted
    # to the correct format with minimal tweaking.
    #
    # Returns the cleaned NMEA string and the variable isGoodStr. If
    # isGoodStr is False, then the returned NMEA string will be set 
    # to be empty.
    #
    # If constant USECHECKSUMS is set to True, then isGoodStr will be
    # False if the calculated checksum does not match the checksum in
    # the NMEA string.
    #
    # e.g.,  msg,isGoodStr = clean_nmea_str(msg)
    isGoodStr = True

    if len(nmeaStr) < 2:
        isGoodStr = False

#    print 'boo3' + nmeaStr
    if nmeaStr[6] != ',':
      nmeaStr = nmeaStr[:6] + nmeaStr[8:]
    #print nmeaStr      
    # NMEA string should start with '$'.
    if isGoodStr == True:
        if nmeaStr[0] != '$':
            # Leading '$' is missing, so this string is not valid.
            isGoodStr = False
    
    # If checksums are known to be present, then it should be safe to
    # remove any extra characters following the checksum (such extra
    # characters have been found in garbled NMEA strings; if they are
    # the only problem with the string, removing them will allow us to
    # salvage the data).
    if isGoodStr == True and USECHECKSUMS == True:
        # Split the string into the core string and the checksum string
        # (following the '*').
        strs = nmeaStr.split('*')

        if len(strs) < 2:
            # String does not have an '*', so it is not valid.
            isGoodStr = False
        else:
            coreStr = strs[0]
            checkSumStr = strs[1]
        
        # The checksum string should be two digits long.
        if isGoodStr == True:
            if len(checkSumStr)<2:
                # Checksum string is too short, so NMEA string is not valid.
                # isGoodStr = False
                isGoodStr = True
            else:
                # Truncate the checksum string if it has extra characters
                # appended to it.
                checkSumStr = checkSumStr[0:2]

                # Re-assemble the NMEA string with the (possibly) truncated
                # checksum string.
                nmeaStr = coreStr + '*' + checkSumStr

    # If requested, check the checksum.
    if isGoodStr == True and USECHECKSUMS == True:

        # Calculate the checksum. Take the bitwise exclusive OR of zero and
        # the first character following the leading '$', then the exclusive
        # OR of the resulting checksum and the second character, and so on.
        checkSum = 0

        for char in coreStr[1:]:
            checkSum = checkSum ^ ord(char)

        # Convert checksum string from hex to decimal.
        try:
            intCheckSum = int(checkSumStr,16)
        except:
            # Conversion of checksum string to integer has
            # failed, probably because of unexpected control 
            # characters. Use a dummy (bad) value of the
            # the checksum.
            intCheckSum = -99

        # If the calculated checksum does not agree with the checksum in the
        # NMEA string, then the string is not valid.
        if checkSum != intCheckSum:
            isGoodStr = False

#    print isGoodStr            
    return nmeaStr, isGoodStr
   
################################################################
# Main program.
################################################################

# Create socket for sending data to computer controlling
# the MVP. Figure 51 in the MVP manual shows there is a single
# IP/Port number pair for all "NAV" data, so this socket will be used
# for both echosounder data and GPS data.
mvpAddr = (mvpControllerIP,udpOutPort)
outUdpSocket = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)

logFid = 0
timeLastLogStarted = float('-inf')

root = Tk()
client = ThreadedClient(root)
root.protocol("WM_DELETE_WINDOW", client.endApplication)
root.mainloop()

# Close outgoing UDP socket.
try:
    outUdpSocket.close()                               
except:
    pass

# Close log file.
if logFid != 0:
    logFid.close()

