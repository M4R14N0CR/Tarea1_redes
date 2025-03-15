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




@implementer(smtp.IMessageDelivery)
class ConsoleMessageDelivery:
    def __init__(self, accepted_domains, storage_path):
        """
        accepted_domains: lista de dominios aceptados (ej. ["midominio.com", "otrodominio.org"])
        storage_path: ruta donde se guardarán los mensajes
        """
        self.accepted_domains = accepted_domains
        self.storage_path = storage_path

    def receivedHeader(self, helo, origin, recipients):
        return "Received: ConsoleMessageDelivery"

    def validateFrom(self, helo, origin):
        # Acepta cualquier dirección de remitente
        return origin

    def validateTo(self, user):
        # Asegurarse de que el dominio sea un string, decodificando si es bytes.
        domain = user.dest.domain.decode('utf-8') if isinstance(user.dest.domain, bytes) else user.dest.domain
        # Asegurarse de que la parte local (usuario) sea un string.
        local = user.dest.local.decode('utf-8') if isinstance(user.dest.local, bytes) else user.dest.local

        # Verifica si el dominio decodificado está en la lista de dominios aceptados.
        if any(domain.lower() == d.lower() for d in self.accepted_domains):
            # Retorna una función lambda que crea un ConsoleMessage pasando el dominio y el usuario decodificados.
            return lambda: ConsoleMessage(domain, local, self.storage_path)
        else:
            raise smtp.SMTPBadRcpt(user)


@implementer(smtp.IMessage)
class ConsoleMessage:
    def __init__(self, domain, user, storage_path):
        """
        domain: Dominio del destinatario (ej. "ejemplo.com")
        user: Parte local del destinatario (ej. "user")
        storage_path: Directorio base donde se almacenarán los correos.
        """
        self.domain = domain
        self.user = user
        self.storage_path = storage_path
        self.lines = []

    def lineReceived(self, line):
        # Decodifica la línea si es de tipo bytes y la añade al acumulador
        if isinstance(line, bytes):
            line = line.decode('utf-8', errors='replace')
        self.lines.append(line)

    def eomReceived(self):
        # Une todas las líneas para formar el mensaje completo
        message = "\n".join(self.lines)
        # Define la ruta de la carpeta: <storage_path>/<dominio>/<usuario>
        destination_folder = os.path.join(self.storage_path, self.domain, self.user)
        # Crea la carpeta (y sus padres) si no existe
        os.makedirs(destination_folder, exist_ok=True)
        # Genera un nombre único para el archivo usando un timestamp
        filename = "message_{}.txt".format(int(time.time() * 1000))
        filepath = os.path.join(destination_folder, filename)
        # Guarda el mensaje en el archivo
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(message)
        print("Mensaje guardado en:", filepath)
        # Limpia las líneas del mensaje
        self.lines = None
        return defer.succeed(None)

    def connectionLost(self):
        # Se llama si la conexión se pierde; se descartan las líneas almacenadas
        self.lines = None


class ConsoleSMTPFactory(smtp.SMTPFactory):
    protocol = smtp.ESMTP

    def __init__(self, portal, delivery, *args, **kwargs):
        smtp.SMTPFactory.__init__(self, *args, **kwargs)
        self.portal = portal
        self.delivery = delivery

    def buildProtocol(self, addr):
        p = smtp.SMTPFactory.buildProtocol(self, addr)
        p.delivery = self.delivery
        p.challengers = {
            b"LOGIN": LOGINCredentials,
            b"PLAIN": PLAINCredentials
        }
        return p


@implementer(IRealm)
class SimpleRealm:
    def __init__(self, delivery):
        self.delivery = delivery

    def requestAvatar(self, avatarId, mind, *interfaces):
        if smtp.IMessageDelivery in interfaces:
            return smtp.IMessageDelivery, self.delivery, lambda: None
        raise NotImplementedError()


def parse_arguments():
    """
    Separa la lectura de argumentos de la línea de comandos.
    """
    parser = argparse.ArgumentParser(description="Servidor SMTP usando Twisted")
    parser.add_argument("-d", "--domains", required=True,
                        help="Dominios aceptados (separados por comas, sin espacios).")
    parser.add_argument("-s", "--mail-storage", required=True,
                        help="Directorio donde se almacenarán los correos.")
    parser.add_argument("-p", "--port", type=int, default=2500,
                        help="Puerto en el que se ejecutará el servidor SMTP (default: 2500).")
    return parser.parse_args()

def main():
    # Obtiene y procesa los argumentos.
    args = parse_arguments()
    domains = [dom.strip() for dom in args.domains.split(',')]
    mail_storage = args.mail_storage
    port = args.port

    print("Iniciando el servidor SMTP con los siguientes parámetros:")
    print("Dominios:", domains)
    print("Almacenamiento:", mail_storage)
    print("Puerto:", port)

    # Configura la instancia de delivery y el portal.
    delivery = ConsoleMessageDelivery(domains, mail_storage)
    portal = Portal(SimpleRealm(delivery))

    # Crea la aplicación Twisted y el factory del servidor.
    app = service.Application("Console SMTP Server")
    factory = ConsoleSMTPFactory(portal, delivery)
    internet.TCPServer(port, factory).setServiceParent(app)

    # Inicia el servicio y arranca el reactor.
    service.IService(app).startService()
    reactor.run()

if __name__ == '__main__':
    main()






