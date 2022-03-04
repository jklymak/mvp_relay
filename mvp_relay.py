"""
mvp_relay--Relays incoming navigation data on multiple serial and/or
UDP ports to MVP controller computer via a single UDP port.

Navigation data includes depthsounder information. The depthsounder on
the Tully transmits a depth of zero whenever it cannot find the
bottom. This causes problems because the MVP controller aborts the
profile if it sees too shallow a depth. The mvp_relay program avfoids
this problem by withholding zero depths from the MVP controller.
"""

import time
import threading
import queue
import socket
import logging
import faulthandler
import signal

faulthandler.register(signal.SIGUSR1)

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.DEBUG)

doSerial=False
################################################################
# These constants can be changed to alter program behaviour:

# Socket parameters for relaying data to MVP controller:
#mvpControllerIP = "142.104.154.118"
mvpControllerIP = "10.248.237.173"
#mvpControllerIP = "192.168.2.160"

# ...MVP controller should be set to listen on this port for
# UDP datagrams.
udpOutPort = 2021
# Port numbers for receiving data via UDP datagram. Echosounder, etc.,
# should be set to send data on these ports. udpInPorts is a list
# variable, with port numbers separated by commas. Can contain zero,
# one or more port numbers.
# Tully 2022:
udpInPorts = [('10.248.237.222', 1025), ('10.248.237.222', 1032)]

# Additional UDP parameters:
udpInBufferLength = 1024 # [bytes]
UDPTIMEOUT = 10 # [seconds]


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
if doSerial:
    import serial

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
DEFAULTDEPTHTIMEOUT = 20000000

# New log files will be created after a certain amount of time has
# passed.
MINUTES_PER_LOG = 60;


# Calculate checksums of NMEA strings. Will only relay datagrams
# to MVP controller if they are valid strings with the correct
# checksum. Set this constant to False if the navigation datagrams
# have no checksums appended to them (in NMEA strings, the checksum
# is a 2-character hex number following an asterisk). If set to
# True and there are no checksums, then NO datagrams will be sent
# to the MVP controller).
USECHECKSUMS = True





class ThreadedClient:
    """
    Launch the main part of the GUI and the worker thread. periodicCall and
    endApplication could reside in the GUI part, but putting them here
    means that you have all the thread controls in a single place.
    """
    def __init__(self):
        """
        Start the asynchronous threads. We are in the main
        (original) thread of the application.
        """

        # Create the queues.
        self.serialQueue = queue.Queue()
        self.udpQueue = queue.Queue()

        self.running = True
        self.num = 1

        for serialInPort in serialInPorts:
            self.serialRelayThreads[serialInPort] = \
                threading.Thread(target=self.serialThread, args=(serialInPort,))
            self.serialRelayThreads[serialInPort].start()

        # Start thread(s) for relaying UDP data to MVP controller.
        self.udpRelayThreads = {} # (dictionary variable)

        # make a listening thread for each udp port
        for udpInPort in udpInPorts:
            logger.info(f'udpInPort {udpInPort}')
            self.udpRelayThreads[udpInPort[1]] = \
                threading.Thread(target=self.udpThread, args=(udpInPort,))
            self.udpRelayThreads[udpInPort[1]].start()

        # Start the periodic call in the GUI to check if the queue contains
        # anything
        self.periodicCall()

    def processIncoming(self):
        """
        Handle all the messages currently in the queue (if any).
        """
        #global lastDepthEpochTime
        #global lastDepthCloseTime

        logger = logging.getLogger('processIncoming')
        qs = [self.udpQueue]
        qnames = ['UDP']

        if doSerial:
            qs += [self.serialQueue]
            qnames += ['Serial']

        for q, qname in zip(qs, qnames):
            logger.debug(f'Processing queue: {qname}')
            qsize = q.qsize()
            logger.debug(f'   queue size: {qsize}')
            if qsize > 0:
                getSucceeded = False
                try:
                    msg = q.get(block=True, timeout=2)
                    logger.debug(f'Get: {msg}')
                    getSucceeded = True
                except queue.Empty:
                    getSucceeded = False

                if getSucceeded:
                    logger.debug('Succeded get')
                    # Log the message without modification, apart from adding
                    # a timestamp.
                    datedMsg = time.strftime("%Y-%m-%d %H:%M:%S",time.localtime()) + '--' + msg
                    datedMsg = datedMsg.rstrip()
                    logMessage(datedMsg)
                    # Relay the message if it is of correct format or if it can be
                    # converted to the correct format with minimal tweaking.
                    try:
                        msgs = msg_split(msg)
                    except:
                        print('grrr')
                    mout = []
                    logger.debug(f'msgs {msgs}')
                    for msg in msgs:
                        m, isGoodStr = clean_nmea_str(msg)
                        if isGoodStr:
                            mout.append(m)
                    logger.debug(f'mout + {mout}')
                    logger.debug('<<<mout')

                    # Relay the message if it is of correct format.
                    if len(mout)>0:
                        for msg in mout:
                            logger.debug(f'relay {msg}')
                            relayMessage(msg)
                    else:
                        self.restart=True

    def periodicCall(self):
        """
        Check every 100 ms if there is something new in the queue and process it.
        """
        try:
            while True:
                self.processIncoming()

                if not self.running:

                    # Wait for serial thread(s) to complete.
                    for serialInPort in self.serialRelayThreads.keys():
                        self.serialRelayThreads[serialInPort].join()

                    # Wait for UDP thread(s) to complete.
                    for udpInPort in self.udpRelayThreads.keys():
                        self.udpRelayThreads[udpInPort].join()

                    import sys
                    sys.exit(1)

                time.sleep(0.1)
        except:
            self.endApplication()

    def serialThread(self,serialInPort):

        # Open serial port.
        try:
            self.ser = serial.Serial(serialInPort,baudRate,\
                                    bytesize=byteSize,parity=parity,\
                                    stopbits=stopBits,timeout=timeOut,\
                                    xonxoff=xonxoff,rtscts=rtscts,\
                                    interCharTimeout=interCharTimeout)
        except:
            print('Failed to open serial port')

        while self.running:

            # Read in data from network.
            serialData = ''

            try:
                serialData = self.ser.readline()
                print(serialData)
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

    def udpThread(self, udpInPort):
        """
        Thread for each udp port to listen and fill the udp queue
        """
        logger = logging.getLogger('udpThread')
        logger.debug('udpInPort is ' + str(udpInPort))

        # Create socket for listening to incoming UDP data.
        relayAddr = udpInPort
        inUdpSocket = socket.socket(socket.AF_INET,socket.SOCK_STREAM)

        while self.running:
            # Read in data from network.
            logger.debug('#### while')

            with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as inUdpSocket:
                inUdpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                inUdpSocket.settimeout(UDPTIMEOUT)
                # ...Bind incoming UDP socket to address of local machine.
                inUdpSocket.connect(relayAddr)

                try:
                    udpData = inUdpSocket.recv(udpInBufferLength)
                    self.num+=1
                    failures = 0
                except:
                    failures += 1
                    logger.warning("Failed UDP receive, trying to reconnect")

                # If UDP connection timed out, then udpData will be empty.
                if len(udpData) > 0:
                    logger.debug(f'udp: {udpData}')
                    logger.debug(f'udp len: {len(udpData)}')
                    # udpData is not empty; echo datagram to GUI.
                    self.udpQueue.put(udpData.decode('utf8'))
                    logger.debug(f'udp put done')


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
        newLogName = 'logs/mvp_relay_' + nowStr + '.log'
        logFid = open(newLogName,'w')
        timeLastLogStarted = time.time()

    msg = msg + '\n'
    logFid.write(msg)
    logFid.flush()

def relayMessage(msg):

    # Determine if this is a depth datagram or not.
    fields = msg.split(',')
    nmeaID = fields[0]
    fields[-1] = fields[-1][:-3]
    logger.debug(f'Fields {fields}')

    logger.debug(f'relayed message: {msg}')

    if nmeaID == "$FKDBS":
        pass
    if nmeaID == "$SDDBS" or nmeaID == "$SDDPT" or nmeaID =='$PKEL9':
        isDepthDataGram = True
    else:
        isDepthDataGram = False

    if len(msg) == 0:
        # Do not send empty datagrams.
        pass
    elif not isDepthDataGram:
        if nmeaID == "$HEHDT":
            pass
        else:
            # Datagram is not a depth datagram.
            try:
                #outUdpSocket.sendto(msg.strip(),mvpAddr)
                logger.info("Out:       "+msg.strip())
                outUdpSocket.sendto((msg.strip()+'\n').encode(), mvpAddr)
                #print "Out OK:       "+msg.strip()
            except:
                print('Send of non-depth datagram to controller computer failed')

    elif nmeaID == "$PKEL9":
        depthStr = fields[5]
        depth = float(depthStr)
        if depth != 0:
            # Depth value is not zero, so it will be relayed to
            # MVP controller. Record the time of this event.
            # Relay message to MVP controller.
            try:
                outUdpSocket.sendto(msg,mvpAddr)
            except:
                print('Send of $SDDBS datagram to controller computer failed')

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
            # Relay message to MVP controller.
            try:
                print("Out:       "+msg)
                outUdpSocket.sendto(msg,mvpAddr)
            except:
                print('Send of $SDDBS datagram to controller computer failed')

    elif nmeaID == "$FKDBS":

        # ...Determine depth from echosounder message.
        depthStr = fields[4]
        depth = float(depthStr)
        print(depth)

        if depth != 0:
            # Depth value is not zero, so it will be relayed to
            # MVP controller. Record the time of this event.
            # Relay message to MVP controller.
            try:
                print("Out:       "+msg)
                outUdpSocket.sendto(msg,mvpAddr)
            except:
                print('Send of $FKDBS datagram to controller computer failed')
    elif nmeaID == "$SDDPT":
        logger.debug('Depth!')
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
        logger.debug(f'msg0 {msg} {fields}')
        depthStr = fields[1]
        offsetStr = fields[2]
        depthBelowT = float(depthStr)
        depthBelowS = depthBelowT + float(offsetStr)
        # ...Relay message to MVP controller.
        msg = msg.strip() + '\n'
        #outUdpSocket.sendto(msg,mvpAddr)
        logger.debug(f'msg {msg}')
        if depthBelowT != 0 and depthBelowS != 0:
            try:
                logger.info("Out depth:  "+msg)
                outUdpSocket.sendto(msg.encode() , mvpAddr)
            except:
                logger.warning('Send of $SDDPT depth datagram to controller computer failed')
        else:
            logger.info('zero depth withheld')

def msg_split(msg):
    mout=[]
    pos2=10
    if msg[0]=='$':
        while pos2 > -1:
            pos = msg.find('$')
            pos2 = msg[pos+1:].find('$')
            mout.append(msg[:pos2])
            msg=msg[pos2+1:]
    return mout

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
    logger.debug(f'START CLEAN {nmeaStr}')
    isGoodStr = True

    if len(nmeaStr) < 9:
        return nmeaStr, False

    if nmeaStr[6] != ',':
      nmeaStr = nmeaStr[:6] + nmeaStr[8:]

    logger.debug(f'START CLEAN {nmeaStr}')
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
            checkSumStr = strs[1][:2]

        # The checksum string should be two digits long.
        if isGoodStr:
            #        isGoodStr == True:
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

        logger.debug(f'core {coreStr} {checkSumStr}')
        for char in coreStr[1:]:
            checkSum = checkSum ^ ord(char)

        # If the calculated checksum does not agree with the checksum in the
        # NMEA string, then the string is not valid.
        newstr = hex(checkSum)[2:].upper()
        if newstr != checkSumStr:
            isGoodStr = False
            logger.debug(f'bad checksum: >>{newstr}<< >>{checkSumStr}<<')
        else:
            logger.debug('good checksum')

    logger.debug('STOP CLEAN')

    return nmeaStr, isGoodStr

################################################################
# Main program.
################################################################

# Create socket for sending data to computer controlling
# the MVP. Figure 51 in the MVP manual shows there is a single
# IP/Port number pair for all "NAV" data, so this socket will be used
# for both echosounder data and GPS data.
logger.info(f'Writing to: {mvpControllerIP}:{udpOutPort}')
mvpAddr = (mvpControllerIP,udpOutPort)
outUdpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

logFid = 0
timeLastLogStarted = float('-inf')

client = ThreadedClient()
#root.protocol("WM_DELETE_WINDOW", client.endApplication)
#root.mainloop()

try:
    while 1:
        time.sleep(0.1)
except:
    logger.info('killing application')
    client.endApplication()


# Close outgoing UDP socket.
try:
    outUdpSocket.close()
except:
    pass

# Close log file.
if logFid != 0:
    logFid.close()
