import socket
import time
HOST = '127.0.0.1'      # Symbolic name meaning the local host
PORT = 23            # Arbitrary non-privileged port

filen = open('GPS.txt','rb')
lines = filen.readlines()
nlines = len(lines)
print nlines
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(('', PORT))



num = 0
while 1:
    s.listen(1)

    conn, addr = s.accept()

    print 'Connected by', addr

    while 1:
        try:
            data = lines[num]
            num+=1
            num = num%nlines
            conn.send(data)
            time.sleep(0.01)
        except:
            conn.close()
            break
            
