from __future__ import print_function
import io
import argparse
import csv
import os

from twisted.internet import reactor, defer, protocol
from twisted.mail import smtp

from email.message import EmailMessage
import email.utils



# Protocolo personalizado para enviar un mensaje SMTP individualmente
class PersonalizedSMTPClient(smtp.ESMTPClient):
    def __init__(self, sender, recipient, message, *args, **kwargs):
        smtp.ESMTPClient.__init__(self, secret=None, identity=sender, *args, **kwargs)
        self.sender = sender
        self.recipient = recipient
        self.message = message
        self.deferred = defer.Deferred()

    def getMailFrom(self):
        # Retorna la dirección del remitente (única vez)
        result = self.sender
        self.sender = None
        return result

    def getMailTo(self):
        # Retorna una lista con la dirección del destinatario
        return [self.recipient]

    def getMailData(self):
        # Devuelve el mensaje como un objeto similar a un archivo
        return io.BytesIO(self.message.encode("utf-8"))

    def sentMail(self, code, resp, numOk, addresses, log):
        print("Mensaje enviado a", self.recipient)
        self.deferred.callback(True)



# Factory para el cliente SMTP que crea el protocolo personalizado
class SMTPClientFactory(protocol.ClientFactory):
    def __init__(self, sender, recipient, message):
        self.sender = sender
        self.recipient = recipient
        self.message = message
        self.deferred = defer.Deferred()

    def buildProtocol(self, addr):
        p = PersonalizedSMTPClient(self.sender, self.recipient, self.message)
        # Cuando el protocolo complete (éxito o error), se propaga al Deferred del factory.
        p.deferred.addBoth(self._finish)
        return p

    def _finish(self, result):
        if not self.deferred.called:
            self.deferred.callback(result)
        return result

    def clientConnectionFailed(self, connector, reason):
        self.deferred.errback(reason)


def parse_arguments():
    """
    Procesa los argumentos de línea de comandos.
    Debido a que -h está reservado para help en argparse, se desactiva el help automático y se
    agrega la opción --help.
    """
    parser = argparse.ArgumentParser(usage="python smtpclient.py -h <mail-server> -c <csv-file> -m <message-file>",
                                     add_help=False)
    parser.add_argument("-h", dest="host", required=True, help="Servidor SMTP al que se conectará")
    parser.add_argument("-c", dest="csv", required=True, help="Archivo CSV con destinatarios (correo,nombre)")
    parser.add_argument("-m", dest="message", required=True,
                        help="Archivo con la plantilla del mensaje (usar {name} para el nombre)")
    parser.add_argument("--help", action="help", help="Mostrar este mensaje de ayuda y salir")
    return parser.parse_args()


@defer.inlineCallbacks
def send_all_emails(host, port, sender, recipients_info, message_template):
    """
    Envía un correo personalizado a cada destinatario de la lista utilizando mensajes en formato MIME.

    recipients_info: lista de tuplas (email, name)
    message_template: plantilla para el cuerpo del mensaje (se espera usar {name} para personalizar)
    """
    deferreds = []
    for recipient_email, name in recipients_info:
        # Construye el mensaje MIME
        msg = EmailMessage()
        msg['Subject'] = "Correo personalizado"  # Puedes parametrizar el asunto si lo deseas.
        msg['From'] = sender
        msg['To'] = recipient_email
        msg['Date'] = email.utils.formatdate(localtime=True)
        msg.set_content(message_template.format(name=name))
        mime_message = msg.as_string()

        print("Enviando correo a:", recipient_email)
        factory = SMTPClientFactory(sender, recipient_email, mime_message)
        reactor.connectTCP(host, port, factory)
        deferreds.append(factory.deferred)
        # (Opcional) Puedes agregar un retardo entre conexiones

    # Espera a que se completen todos los envíos
    results = yield defer.DeferredList(deferreds, consumeErrors=True)
    for success, result in results:
        if success:
            print("Envio exitoso.")
        else:
            print("Error en el envío:", result)
    reactor.stop()


def main():
    # Procesa los argumentos
    args = parse_arguments()
    host = args.host
    csv_file = args.csv
    message_file = args.message

    # Define el remitente (puedes parametrizarlo si lo deseas)
    sender = "tutorial_sender@example.com"
    port = 2500  # Puedes parametrizar el puerto si se requiere

    # Carga la lista de destinatarios desde el archivo CSV
    recipients_info = []
    with open(csv_file, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        # Se espera que cada línea tenga: correo, nombre
        for row in reader:
            if len(row) >= 2:
                email = row[0].strip()
                name = row[1].strip()
                recipients_info.append((email, name))

    if not recipients_info:
        print("No se encontraron destinatarios en el CSV.")
        return

    # Lee la plantilla del mensaje
    if not os.path.exists(message_file):
        print("El archivo de mensaje no existe.")
        return

    with open(message_file, 'r', encoding='utf-8') as mf:
        message_template = mf.read()

    # Lanza el envío de todos los correos y arranca el reactor
    send_all_emails(host, port, sender, recipients_info, message_template)
    reactor.run()


if __name__ == '__main__':
    main()
