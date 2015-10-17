import socket as socket

address = '127.0.0.1'
port = 50008

s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
s.connect((address,port))
while 1:
    data = s.recv(1024)
    print data
s.close()
