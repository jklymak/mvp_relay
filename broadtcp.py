import socket
import time
HOST = '127.0.0.1'      # Symbolic name meaning the local host
PORT = 23            # Arbitrary non-privileged port

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(('', PORT))
s.listen(1)
conn, addr = s.accept()

print 'Connected by', addr
num = 0

while 1:
    try:
        data = 'Boo Hi! %d\n'%num
        num+=1
        
        conn.send(data)
        time.sleep(0.05)
    except:
        break
