import socket
import time
HOST = '127.0.0.1'      # Symbolic name meaning the local host
PORT = 26            # Arbitrary non-privileged port

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(('', PORT))

num = 0
while 1:
    s.listen(1)

    conn, addr = s.accept()

    print 'Connected by', addr

    while 1:
        try:
            data = 'Boo H2! %d\n'%num
            num+=1
        
            conn.send(data)
            time.sleep(0.5)
        except:
            conn.close()
            break
            
