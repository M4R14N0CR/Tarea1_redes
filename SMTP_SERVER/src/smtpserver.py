import os
import time
import argparse
from twisted.mail import smtp
from twisted.internet import defer
from twisted.internet import reactor
from twisted.cred.portal import Portal
from zope.interface import implementer
from twisted.cred.portal import IRealm
from twisted.application import internet, service
from twisted.mail.imap4 import LOGINCredentials, PLAINCredentials



#Clase que implementa la interfaz IMessageDelivery de Twisted para gestionar la entrega de mensajes
@implementer(smtp.IMessageDelivery)
class MessageDelivery:

    # Constructor:
    # accepted_domains: lista de dominios que se aceptan
    # storage_path: ruta del directorio donde se almacenarán los correos
    def __init__(self, accepted_domains, storage_path):
        self.accepted_domains = accepted_domains
        self.storage_path = storage_path

    # Método que retorna un encabezado "Received" para el mensaje.
    # Entrada: helo (saludo del cliente), origin (dirección del remitente), recipients (destinatarios)
    # Salida: cadena de texto con el encabezado recibido
    def receivedHeader(self, helo, origin, recipients):
        return "Received: ConsoleMessageDelivery"

    # Método para validar la dirección de origen.
    # Entrada: helo (saludo del cliente), origin (dirección del remitente)
    # Salida: retorna la dirección de origen sin modificaciones
    # Permite recibir correos de cualquier dominio
    def validateFrom(self, helo, origin):

        return origin

    # Método para validar el destinatario.
    # Entrada: user (objeto que contiene información sobre el destinatario)
    # Salida: función lambda que crea una instancia de ConsoleMessage si el dominio es aceptado;
    # de lo contrario, lanza una excepción SMTPBadRcpt
    def validateTo(self, user):

        # Se obtiene el dominio y la parte local del destinatario, decodificando de bytes a str si es necesario.
        domain = user.dest.domain.decode('utf-8') if isinstance(user.dest.domain, bytes) else user.dest.domain
        local = user.dest.local.decode('utf-8') if isinstance(user.dest.local, bytes) else user.dest.local

        if any(domain.lower() == d.lower() for d in self.accepted_domains):
            return lambda: Message(domain, local, self.storage_path)
        else:
            raise smtp.SMTPBadRcpt(user)

# Clase que implementa la interfaz IMessage para representar y procesar un mensaje SMTP
@implementer(smtp.IMessage)
class Message:
    # Constructor:
    # domain: dominio del destinatario
    # user: parte local del destinatario
    # storage_path: ruta base para almacenar el mensaje
    def __init__(self, domain, user, storage_path):
        self.domain = domain
        self.user = user
        self.storage_path = storage_path
        self.lines = []

    # Método que se invoca por cada línea recibida del mensaje
    # Entrada: line (línea del mensaje, puede ser bytes o str)
    # No tiene salida, solo agrega la línea procesada a la lista.
    def lineReceived(self, line):
        if isinstance(line, bytes):
            line = line.decode('utf-8', errors='replace')
        self.lines.append(line)

    # Método que se invoca al finalizar la recepción del mensaje
    # Salida: retorna un Deferred que se resuelve exitosamente.
    def eomReceived(self):
        message = "\n".join(self.lines)
        destination_folder = os.path.join(self.storage_path, self.domain, self.user) # Construye la ruta del directorio destino: storage_path/dominio/usuario
        os.makedirs(destination_folder, exist_ok=True)
        filename = "message_{}.eml".format(int(time.time() * 1000))
        filepath = os.path.join(destination_folder, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(message)
        print("Mensaje guardado en:", filepath)
        self.lines = None
        return defer.succeed(None)

    def connectionLost(self):
        self.lines = None

# Clase que extiende SMTPFactory para crear un servidor SMTP personalizado.
class NewSMTPFactory(smtp.SMTPFactory):
    protocol = smtp.ESMTP

    # Constructor:
    # portal: instancia de Portal para gestionar autenticaciones.
    # delivery: instancia de MessageDelivery para gestionar la entrega de mensajes.
    # *args, **kwargs: argumentos adicionales para el constructor de la clase base.
    def __init__(self, portal, delivery, *args, **kwargs):
        smtp.SMTPFactory.__init__(self, *args, **kwargs)
        self.portal = portal
        self.delivery = delivery

    # Método que construye el protocolo SMTP para cada conexión entrante.
    # Entrada: addr (dirección del cliente)
    # Salida: instancia del protocolo SMTP configurado.
    def buildProtocol(self, addr):
        p = smtp.SMTPFactory.buildProtocol(self, addr)
        p.delivery = self.delivery
        p.challengers = {
            b"LOGIN": LOGINCredentials,
            b"PLAIN": PLAINCredentials
        }
        return p


# Clase que implementa la interfaz IRealm para la autenticación y autorización de usuarios.
@implementer(IRealm)
class SimpleRealm:
    # Constructor:
    # delivery: instancia de MessageDelivery que se usará para manejar mensajes.
    def __init__(self, delivery):
        self.delivery = delivery

    # Método para solicitar un avatar
    # Entrada: avatarId, mind, interfaces
    # Salida: retorna una tupla (interfaz, objeto, función de desconexión) si se solicita IMessageDelivery;
    # si no, lanza NotImplementedError.
    def requestAvatar(self, avatarId, mind, *interfaces):
        if smtp.IMessageDelivery in interfaces:
            return smtp.IMessageDelivery, self.delivery, lambda: None
        raise NotImplementedError()


# Función para parsear los argumentos de la línea de comandos.
# No recibe argumentos y retorna un objeto con los parámetros:
# - domains: dominios aceptados (cadena separada por comas)
# - mail-storage: directorio de almacenamiento de correos
# - port: puerto del servidor SMTP
def parse_arguments():
    parser = argparse.ArgumentParser(description="Servidor SMTP usando Twisted")
    parser.add_argument("-d", "--domains", required=True,
                        help="Dominios aceptados (separados por comas, sin espacios).")
    parser.add_argument("-s", "--mail-storage", required=True,
                        help="Directorio donde se almacenarán los correos.")
    parser.add_argument("-p", "--port", type=int, default=2500,
                        help="Puerto en el que se ejecutará el servidor SMTP (default: 2500).")
    return parser.parse_args()

#Funcion principal que arranca el servidor SMTP
def main():

    args = parse_arguments()
    domains = [dom.strip() for dom in args.domains.split(',')]
    mail_storage = args.mail_storage
    port = args.port

    print("Iniciando el servidor SMTP con los siguientes parámetros:")
    print("Dominios:", domains)
    print("Almacenamiento:", mail_storage)
    print("Puerto:", port)

    delivery = MessageDelivery(domains, mail_storage)
    portal = Portal(SimpleRealm(delivery))

    app = service.Application("Console SMTP Server")
    factory = NewSMTPFactory(portal, delivery)
    internet.TCPServer(port, factory).setServiceParent(app)

    service.IService(app).startService()
    reactor.run()

if __name__ == '__main__':
    main()
