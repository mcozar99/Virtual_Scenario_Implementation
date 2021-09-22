import sys
from subprocess import call
from lxml import etree
import os

#Introduzca el nombre del directorio en uso
directorio='/home/m.cozar'


# String con la configuracion de rc.local, a usar posteriormente

rconf= """
#!/bin/bash

service apache2 stop

sudo service haproxy restart

exit 0

"""

# String con la configuracion de balanceo de carga de lb como roundrobin

lbconf="""
global
	log /dev/log	local0
	log /dev/log	local1 notice
	chroot /var/lib/haproxy
	stats socket /run/haproxy/admin.sock mode 660 level admin expose-fd listeners
	stats timeout 30s
	user haproxy
	group haproxy
	daemon

	# Default SSL material locations
	ca-base /etc/ssl/certs
	crt-base /etc/ssl/private

	# Default ciphers to use on SSL-enabled listening sockets.
	# For more information, see ciphers(1SSL). This list is from:
	#  https://hynek.me/articles/hardening-your-web-servers-ssl-ciphers/
	# An alternative list with additional directives can be obtained from
	#  https://mozilla.github.io/server-side-tls/ssl-config-generator/?server=haproxy
	ssl-default-bind-ciphers ECDH+AESGCM:DH+AESGCM:ECDH+AES256:DH+AES256:ECDH+AES128:DH+AES:RSA+AESGCM:RSA+AES:!aNULL:!MD5:!DSS
	ssl-default-bind-options no-sslv3

defaults
	log	global
	mode	http
	option	httplog
	option	dontlognull
        timeout connect 5000
        timeout client  50000
        timeout server  50000
	errorfile 400 /etc/haproxy/errors/400.http
	errorfile 403 /etc/haproxy/errors/403.http
	errorfile 408 /etc/haproxy/errors/408.http
	errorfile 500 /etc/haproxy/errors/500.http
	errorfile 502 /etc/haproxy/errors/502.http
	errorfile 503 /etc/haproxy/errors/503.http
	errorfile 504 /etc/haproxy/errors/504.http

frontend lb
	bind *:80
	mode http
	default_backend webservers

listen stats
	bind :8001
	stats enable
	stats uri /
	stats hide-version
	stats auth cdps:cdps	

backend webservers
	mode http
	balance roundrobin
"""

# Strings con las configuraciones de hosts de cada maquina virtual

etchosts = "127.0.0.1 localhost\n\n\n::1 ip6-localhost ip6-loopback\nfe00::0 ip6-localnet\nff00::0 ip6-mcastprefix\nff02::1 ip6-allnodes\nff02::2 ip6-allrouters\nff02::3 ip6-allhosts"
networkinterfaces =  'auto lo\niface lo inet loopback\n\nauto eth0\niface eth0 inet static\n'

# Array con los ips de todas las MVs para emplearlo en el ping
ips=["10.0.1.1", "10.0.2.1", "10.0.1.2", "10.0.2.11", "10.0.2.12", "10.0.2.13", "10.0.2.14", "10.0.2.15"]
maquinasping=["lb lan1", "lb lan2", "c1", "s1", "s2", "s3", "s4", "s5"]

def modificaXML(fichero, nombre, source, bridge):   # Metodo que modifica el fichero base xml
    tree = etree.parse(fichero)
    root = tree.getroot()
    name = root.find("name")
    name.text = nombre
    fuente = root.find("./devices/disk[@type='file']/source")
    fuente.set("file", source)
    puente = root.find("./devices/interface[@type='bridge']/source")
    puente.set("bridge", bridge)
    if (nombre == "lb"):                    # Si se trata del balanceador de carga deberemos crear un nuevo interface
        devices = root.find("devices")
        inter = etree.Element("interface")
        inter.set("type", 'bridge')
        var = etree.Element("source")
        var.set("bridge", 'LAN2')
        model = etree.Element("model")
        model.set("type", 'virtio')
        inter.append(var)
        inter.append(model)
        devices.append(inter)
    f = open(fichero, "w")
    f.write(etree.tounicode(tree, pretty_print=True))
    f.close()


# Este metodo configura el LB como un balanceador de carga, creamos haproxy.cfg y rc.local a partir de los strings que
# hemos creado al principio del script y en funcion del numero de servidores la configuracion es una u otra.
# Se aprovecha el metodo tambien para crear un fichero index.html que escriba el nombre de cada servidor en la pagina
# principal de cada uno. Esto nos sirve mas adelante a la hora de comprobar el balanceo de carga con curl

def balanceoHAProxy(n):
    haproxy = open('/mnt/tmp/haproxy.cfg', 'w')
    rcconf = open('/mnt/tmp/rc.local', 'w')
    rcconf.write(rconf)
    haproxy.write(lbconf)
    for i in range(int(n)):
	serv = open('/mnt/tmp/index.html', 'w')
	serv.write('S' + str(i+1) + '\n')
	serv.close()
	call(['sudo', 'virt-copy-in', '-a', 's' + str(i+1) + ".qcow2", '/mnt/tmp/index.html', '/var/www/html'])
	call(['rm', '/mnt/tmp/index.html'])
	s= str(i+1)
	haproxy.write("\tserver s"+s+" 10.0.2.1"+s+ ":80 check\n")
    haproxy.close()
    call(['sudo', 'virt-copy-in', '-a', "lb.qcow2", '/mnt/tmp/haproxy.cfg', '/etc/haproxy'])
    call(['sudo', 'virt-copy-in', '-a', "lb.qcow2", '/mnt/tmp/rc.local', '/etc/'])
    call(['rm', '/mnt/tmp/haproxy.cfg'])
    call(['rm', '/mnt/tmp/rc.local'])

def configuraHost():
    call(['sudo', 'ifconfig','LAN1', '10.0.1.3/24'])
    call(['sudo', 'ip', 'route', 'add', '10.0.0.0/16', 'via', '10.0.1.1'])


def configuraMV(maquina):
    hostname = open('/mnt/tmp/hostname', 'w')       # creamos los tres ficheros a editar en un directorio temporal
    hosts = open('/mnt/tmp/hosts', 'w')
    interfaces = open('/mnt/tmp/interfaces', 'w')
    hostname.write(maquina)                         # editamos hostname para cambiar el prompt
    hosts.write('127.0.1.1    ' + maquina+ '\n' + etchosts)     #cambiamos el fichero hosts como se hizo en el laboratorio 3
    interfaces.write(networkinterfaces)
    mask = '255.255.255.0'                  #la mask es siempre la misma
    if maquina == 'c1':                     #asignamos las ips y gateways que corresponden a cada elemento del sistema
        address = '10.0.1.2'
        gateway = '10.0.1.1'
    elif maquina == 's1':
        address = '10.0.2.11'
        gateway = '10.0.2.1'
    elif maquina == 's2':
        address = '10.0.2.12'
        gateway = '10.0.2.1'
    elif maquina == 's3':
        address = '10.0.2.13'
        gateway = '10.0.2.1'
    elif maquina == 's4':
        address = '10.0.2.14'
        gateway = '10.0.2.1'
    elif maquina == 's5':
        address = '10.0.2.15'
        gateway = '10.0.2.1'
    elif maquina == 'lb':
        address = '10.0.1.1'
        address2 = '10.0.2.1'
        #gateway = ''
    if maquina != 'lb':
   	interfaces.write('address ' + address + '\nnetmask ' + mask + '\ngateway '+ gateway +'\n')  #modificamos el fichero interfaces
    if maquina == 'lb':
	interfaces.write('\taddress ' + address + '\n\tnetmask ' + mask + '\n')
        interfaces.write('\nauto eth1\niface eth1 inet static\n\taddress '+ address2 + '\n\tnetmask ' + mask + '\n')
    interfaces.close()
    hostname.close()
    hosts.close()
    qcow = maquina + '.qcow2'               #copiamos los ficheros a la MV y los borramos del directorio temporal
    call(['sudo', 'virt-copy-in', '-a', qcow, '/mnt/tmp/hostname', '/etc'])
    call(['sudo', 'virt-copy-in', '-a', qcow, '/mnt/tmp/hosts', '/etc'])
    call(['sudo', 'virt-copy-in', '-a', qcow, '/mnt/tmp/interfaces', '/etc/network'])
    call(['rm', '/mnt/tmp/interfaces'])
    call(['rm', '/mnt/tmp/hosts'])
    call(['rm', '/mnt/tmp/hostname'])

    if maquina == 'lb':             #configuramos el LB como router
	f=open("/mnt/tmp/sysctl.conf","w")
	f.write('net.ipv4.ip_forward=1')
	f.close()
	call(['sudo', 'virt-copy-in', '-a', "lb.qcow2", '/mnt/tmp/sysctl.conf', '/etc'])



def empieza(maquina):               # Metodo que define e inicia el dominio de una maquina e inicializa su consola
    fichero = maquina + '.xml'
    call(['sudo', 'virsh', 'define', fichero])
    call(['sudo', 'virsh', 'start', maquina])
    call(['xterm', '-e', "sudo virsh console %s" %maquina])
    print(maquina + ' iniciada')


def listaMV():                      # Metodo que crea un array con la lista de MVs que tenemos creadas
    lista = ['lb', 'c1']            # c1 y lb son predeterminadas
    f = open('pc1.cfg', 'r')
    for line in f:                  # Leemos el numero de servidores que tenemos en el fichero cfg
        fields = line.strip().split('=')
        num_serv = fields[1]
    f.close()
    i = 1
    while i <= int(num_serv):   # Los metemos a la lista con su nombre correspondiente
        a = 's' + str(i)
        lista.append(a)
        i += 1
    return lista

def paraMV(maquina):
    call(['sudo', 'virsh', 'shutdown', maquina])
    print(maquina + ' parada')

def create(n):
    f = open('pc1.cfg', 'w')                    # Anotamos el numero de servidores en nuestro fichero cfg
    f.write('num_serv=' + str(n)+'\n')
    f.close()
    call(['qemu-img', 'create', '-f', 'qcow2', '-b', 'cdps-vm-base-pc1.qcow2', 'lb.qcow2'])     #Creamos las imagenes y xml de lb y c1 y modificamos el xml
    call(['qemu-img', 'create', '-f', 'qcow2', '-b', 'cdps-vm-base-pc1.qcow2', 'c1.qcow2'])
    call(['cp', 'plantilla-vm-pc1.xml', 'lb.xml'])
    modificaXML('lb.xml', 'lb', '%s/pc1/lb.qcow2' %directorio, 'LAN1')
    call(['cp', 'plantilla-vm-pc1.xml', 'c1.xml'])
    modificaXML('c1.xml', 'c1', '%s/pc1/c1.qcow2' %directorio, 'LAN1')
    for i in range(1, int(n)+1):            #Hacemos lo mismo para el numero de servidores que hayamos ordenado
        str1 = 's' + str(i) + '.qcow2'
        str2 = 's' + str(i) + '.xml'
        nombre = 's' + str(i)
        call(['qemu-img', 'create', '-f', 'qcow2', '-b', 'cdps-vm-base-pc1.qcow2', str1])
        call(['cp', 'plantilla-vm-pc1.xml', str2])
        str1 = directorio + '/pc1/s' + str(i) + '.qcow2'
        modificaXML(str2, nombre, str1, 'LAN2')

    call(['sudo', 'brctl', 'addbr', 'LAN1'])    #Configuramos los bridges y las interfaces LAN
    call(['sudo', 'brctl', 'addbr', 'LAN2'])
    call(['sudo', 'ifconfig', 'LAN1', 'up'])
    call(['sudo', 'ifconfig', 'LAN2', 'up'])
    lista = listaMV()
    for maquina in listaMV():
        configuraMV(maquina)
    configuraHost()
    balanceoHAProxy(n)


def start():
    lista = listaMV()               # Recogemos el numero de maquinas del escenario
    if sys.argv[2] in lista:    # Proteccion frente a comandos invalidos
	empieza(sys.argv[2])
    else:
        print('Comando Invalido')


def startAll():
    lista = listaMV()
    for maquina in lista:
	fichero = maquina + '.xml'
	call(['sudo', 'virsh', 'define', fichero])
	call(['sudo', 'virsh', 'start', maquina])
	os.system("xterm -e \'sudo virsh console %s \'&" %maquina)


def stop():
    lista = listaMV()               # Recogemos el numero de maquinas del escenario
    if sys.argv.__len__() == 2:     # Podemos parar todas las maquinas a la vez o...
        for maquina in lista:
            paraMV(maquina)
    elif sys.argv.__len__() == 3:   # Si queremos podemos especificar cual queremos parar
        if sys.argv[2] in lista:
            paraMV(sys.argv[2])
        else:
            print('Comando invalido')
    else:
        print('Comando Invalido')

def release():
    lista = listaMV()               # Recogemos el numero de maquinas del escenario
    for maquina in lista:           # Una a una vamos borrando tanto sus imagenes como xml, ademas de destruir su dominio
        call(['sudo', 'virsh', 'destroy', maquina])
	call(['sudo', 'virsh', 'undefine', maquina])
        xml = maquina + '.xml'
        qcow = maquina + '.qcow2'
        call(['rm', xml])
        call(['rm', qcow])
        print(maquina + ' destruida')
    call(['rm', 'pc1.cfg'])	    # borramos el fichero de configuracion que guarda el numero de servidores
    call(['sudo', 'ifconfig', 'LAN1', 'down'])   #Eliminamos los bridges y las interfaces LAN
    call(['sudo', 'ifconfig', 'LAN2', 'down'])
    call(['sudo', 'brctl', 'delbr', 'LAN1'])   
    call(['sudo', 'brctl', 'delbr', 'LAN2'])
    print('Se han destruido todas las imagenes qcow2 y los ficheros xml, asi como el fichero de configuracion,los bridges y las interfaces LAN')

# Se realiza un ping a todas las MVs en marcha

def ping():
    lista=listaMV()
    i=0
    while i<=lista.__len__():
    	print("PING a " + maquinasping[i])
    	call(['ping', '-c', '3', ips[i]])
	i=i+1
	print("\n")

# Metodo que monitoriza todas las maquinas virtuales en activo. Las lista y da datos acerca de sus dominios y CPUs

def monitor():
    print("Lista de maquinas arrancadas\n")
    call(['sudo', 'virsh', 'list'])
    for maquina in listaMV():
	print("\nInfo sobre el dominio " + maquina +"\n")
	call(['sudo', 'virsh', 'dominfo', maquina])
	print("\nEstadisticas de las CPUs de " + maquina + "\n")
	call(['sudo', 'virsh', 'cpu-stats', maquina])   

def help():
    print("\nEstan disponibles los siguientes comandos:")
    print("\n")
    print("\ncreate - Crea todas las MVs y realiza sus respectivas configuraciones.")
    print("\nstart & - Pone en marcha todas las MVs creadas.")
    print("\nstart <nombre-maquina> & - Pone en marcha la MV deseada.")
    print("\nstop - Detiene la ejecucion de todas las MVs.")
    print("\nstop <nombre-maquina> - Detiene la ejecucion de la MV deseada.")
    print("\nrelease - Elimina las MVs, LANs y configuraciones realizadadas.")
    print("\nping - Realiza un ping a las MVs previamente creadas.")
    print("\nmonitor - Muestra informacion y monitoriza las MVs creadas.")
    print("\nbalance - Realiza peticiones al servidor cada 0.5s para comprobar la funcionalidad del balanceador\n\n")

    


if sys.argv[1] == 'create':
    if(sys.argv.__len__() == 3):    #Configuracion del numero de servidores que vamos a crear
        if(int(sys.argv[2])>5):
            print('Has indicado mas servidores de los que se permiten, solo crearemos 2')
            create(2)
        else:
            create(sys.argv[2])
    else:
        create(2)

if sys.argv[1] == 'start':  #indicamos en sys.argv[2] la MV que queremos inicar o se inician todas
	if sys.argv.__len__() == 2:
		startAll()
	else:
		start()

if sys.argv[1] == 'stop':
    stop()

if sys.argv[1] == 'release':
    release()

if sys.argv[1] == 'ping':
    ping()

if sys.argv[1] == 'monitor':
    monitor()

if sys.argv[1] == 'help': 
    help()

if sys.argv[1] == 'balance':
    print('Se va a hacer una peticion al servidor cada 0.5 s. \nComprobar las estadisticas de balanceo en:\nhttp://10.0.1.1:8001\nusuario: cdps\ncontrasena: cdps')
    call("(while true; do curl 10.0.1.1; sleep 0.5; done)", shell=True)
