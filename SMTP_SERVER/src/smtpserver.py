import argparse
from twisted.application import internet, service
from zope.interface import implementer
from twisted.internet import defer
from twisted.mail import smtp
from twisted.mail.imap4 import LOGINCredentials, PLAINCredentials
from twisted.cred.checkers import InMemoryUsernamePasswordDatabaseDontUse
from twisted.cred.portal import IRealm
from twisted.cred.portal import Portal
import os
import time
from twisted.internet import reactor


@implementer(smtp.IMessageDelivery)
class ConsoleMessageDelivery:
    def receivedHeader(self, helo, origin, recipients):
        return "Received: ConsoleMessageDelivery"

    def validateFrom(self, helo, origin):

        return origin

    def validateTo(self, user):
        # Only messages directed to the "console" user are accepted.
        #if user.dest.local == "console":
        return lambda: ConsoleMessage()
        #raise smtp.SMTPBadRcpt(user)


@implementer(smtp.IMessage)
class ConsoleMessage:
    def __init__(self,domain,storage_path):
        self.storage_path = storage_path
        self.lines = []

    def lineReceived(self, line):
        if isinstance(line, bytes):
            line = line.decode('utf-8', errors='replace')
        self.lines.append(line)

    def eomReceived(self):

        message = "\n".join(self.lines)
        filename = "message_{}.txt".format(int(time.time() * 1000))
        filepath = os.path.join(self.storage_path, filename)

        os.makedirs(self.storage_path, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(message)
        print("Mensaje guardado en:", filepath)
        self.lines = None
        return defer.succeed(None)

    def connectionLost(self):

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
        p.challengers = {"LOGIN": LOGINCredentials, "PLAIN": PLAINCredentials}
        return p


@implementer(IRealm)
class SimpleRealm:
    def __init__(self, delivery):
        self.delivery = delivery

    def requestAvatar(self, avatarId, mind, *interfaces):
        if smtp.IMessageDelivery in interfaces:
            return smtp.IMessageDelivery, self.delivery, lambda: None
        raise NotImplementedError()


def main(domains, mail_storage, port):
    portal = Portal(SimpleRealm())
    checker = InMemoryUsernamePasswordDatabaseDontUse()
    checker.addUser("guest", "password")
    portal.registerChecker(checker)

    app = service.Application("Console SMTP Server")

    factory = ConsoleSMTPFactory(portal, domains, mail_storage)

    internet.TCPServer(port, factory).setServiceParent(app)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Servidor SMTP usando Twisted")
    parser.add_argument("-d", "--domains", required=True,
                        help="Dominios aceptados (separados por comas, sin espacios).")
    parser.add_argument("-s", "--mail-storage", required=True,
                        help="Directorio donde se almacenarán los correos.")
    parser.add_argument("-p", "--port", type=int, default=2500,
                        help="Puerto en el que se ejecutará el servidor SMTP (default: 2500).")

    args = parser.parse_args()


    domains = [dom.strip() for dom in args.domains.split(',')]
    mail_storage = args.mail_storage
    port = args.port

    print("Iniciando el servidor SMTP con los siguientes parámetros:")
    print("Dominios:", domains)
    print("Almacenamiento:", mail_storage)
    print("Puerto:", port)


    application = main(domains, mail_storage, port)
    service.IService(application).startService()
    reactor.run()