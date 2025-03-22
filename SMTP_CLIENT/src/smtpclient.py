from __future__ import print_function
import io
import argparse
import csv
import os

from twisted.internet import reactor, defer, protocol
from twisted.mail import smtp

from email.message import EmailMessage
import email.utils



# Clase que extiende de smtp.ESMTPClient para definir un cliuente SMTP que envia
# un mensaje de correo individual.
class PersonalizedSMTPClient(smtp.ESMTPClient):

    # Constructor:
    # sender: dirección de correo del remitente.
    # recipient: dirección de correo del destinatario.
    # message: mensaje (plantilla) a enviar.
    # *args, **kwargs: argumentos adicionales que se pasan a la clase base.
    def __init__(self, sender, recipient, message, *args, **kwargs):
        smtp.ESMTPClient.__init__(self, secret=None, identity=sender, *args, **kwargs)
        self.sender = sender
        self.recipient = recipient
        self.message = message
        self.deferred = defer.Deferred()

    # Método que retorna el remitente del correo.
    # Se devuelve la dirección y se limpia el atributo para evitar reutilización.
    def getMailFrom(self):

        result = self.sender
        self.sender = None
        return result

    # Método que retorna la lista de destinatarios.
    def getMailTo(self):

        return [self.recipient]

    # Método que retorna el contenido del mensaje.
    # Se devuelve un objeto BytesIO conteniendo el mensaje codificado en UTF-8.
    def getMailData(self):

        return io.BytesIO(self.message.encode("utf-8"))

    # Método llamado cuando el correo se ha enviado exitosamente.
    # Los parámetros incluyen el código de respuesta, respuesta del servidor, cantidad de direcciones aceptadas,
    # lista de direcciones y log.
    # Se marca el Deferred como exitoso.
    def sentMail(self, code, resp, numOk, addresses, log):

        self.deferred.callback(True)



# Clase que extiende de CLientFactory, se encarga de crear instancias de clientes para cada conexion al servidor SMTP.
class SMTPClientFactory(protocol.ClientFactory):

    # Constructor:
    # sender: dirección del remitente.
    # recipient: dirección del destinatario.
    # message: mensaje a enviar.
    def __init__(self, sender, recipient, message):
        self.sender = sender
        self.recipient = recipient
        self.message = message
        self.deferred = defer.Deferred()

    # Método para construir el protocolo SMTP personalizado para la conexión.
    # Entrada: addr (dirección del servidor)
    # Salida: instancia de PersonalizedSMTPClient.
    def buildProtocol(self, addr):
        p = PersonalizedSMTPClient(self.sender, self.recipient, self.message)
        p.deferred.addBoth(self._finish)
        return p

    # Método interno para finalizar el proceso, callback compartido.
    # Se encarga de notificar el Deferred general de la fábrica.
    def _finish(self, result):
        if not self.deferred.called:
            self.deferred.callback(result)
        return result

    # Método llamado si la conexión falla.
    # Se notifica el Deferred con un error.
    def clientConnectionFailed(self, connector, reason):
        self.deferred.errback(reason)

#Esta función se encarga de enviar correos electrónicos a todos los destinatarios listados en el CSV de forma asíncrona.
# host: Dominio del servidor SMTP al que se conectara
# port: Puerto al que se conectara al servidor
# sender: El remitente que envia el correo
# recipients_info: Informacion del usuario destinatario
# message_template: Plantilla del correo
@defer.inlineCallbacks
def send_all_emails(host, port, sender, recipients_info, message_template):

    deferreds = []
    for recipient_email, name in recipients_info:

        msg = EmailMessage()
        msg['Subject'] = "Correo personalizado"
        msg['From'] = sender
        msg['To'] = recipient_email
        msg['Date'] = email.utils.formatdate(localtime=True)
        msg.set_content(message_template.format(name=name))
        mime_message = msg.as_string()

        print("Enviando correo a:", recipient_email)
        factory = SMTPClientFactory(sender, recipient_email, mime_message)
        reactor.connectTCP(host, port, factory)
        deferreds.append(factory.deferred)



    results = yield defer.DeferredList(deferreds, consumeErrors=True)
    for success, result in results:
        if success:
            print("Envio exitoso.")
        else:
            print("Error en el envío:", result)
    reactor.stop()

# Función para parsear los argumentos de la línea de comandos.
# No recibe argumentos y retorna un objeto con los parámetros:
# - host: Servidor SMTP al que se conectara
# - csv: Direccion del archivo CSV con los destinatarios
# - message-file: Archivo con la plantilla del mensaje que se enviara en el correo
def parse_arguments():

    parser = argparse.ArgumentParser(usage="python smtpclient.py -h <mail-server> -c <csv-file> -m <message-file>",
                                     add_help=False)
    parser.add_argument("-h", dest="host", required=True, help="Servidor SMTP al que se conectará")
    parser.add_argument("-c", dest="csv", required=True, help="Archivo CSV con destinatarios (correo,nombre)")
    parser.add_argument("-m", dest="message", required=True,
                        help="Archivo con la plantilla del mensaje (usar {name} para el nombre)")
    parser.add_argument("--help", action="help", help="Mostrar este mensaje de ayuda y salir")
    return parser.parse_args()


# Funcion principal que envia los correos masivamente
def main():
    args = parse_arguments()
    host = args.host
    csv_file = args.csv
    message_file = args.message


    sender = "tutorial_sender@example.com"
    port = 2525


    recipients_info = []
    with open(csv_file, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)

        for row in reader:
            if len(row) >= 2:
                email = row[0].strip()
                name = row[1].strip()
                recipients_info.append((email, name))

    if not recipients_info:
        print("No se encontraron destinatarios en el CSV.")
        return


    if not os.path.exists(message_file):
        print("El archivo de mensaje no existe.")
        return

    with open(message_file, 'r', encoding='utf-8') as mf:
        message_template = mf.read()


    send_all_emails(host, port, sender, recipients_info, message_template)
    reactor.run()


if __name__ == '__main__':
    main()
