import socket as socket

address = '10.248.237.222'
port = 1025

s=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((address,port))
while 1:
    data = s.recv(1024)
    print(data)
s.close()
