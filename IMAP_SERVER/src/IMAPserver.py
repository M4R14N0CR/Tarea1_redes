from twisted.internet import reactor, defer, protocol
from twisted.mail import imap4
from zope.interface import implementer
import os
import argparse
import email.utils
from email.parser import HeaderParser
from io import BytesIO
import csv
from twisted.cred import portal, credentials, checkers, error as credError

# Clase que encapsula los detalles de un correo electrónico, ofreciendo métodos para obtener información
# relevante del mensaje para el funcionamiento del protocolo IMAP.
@implementer(imap4.IMessage)
class SimpleMessage:

    # Constructor:
    # content: contenido completo del mensaje (texto)
    # uid: identificador único del mensaje
    def __init__(self, content, uid):
        self.content = content
        self.uid = uid

    # Devuelve el UID del mensaje.
    def getUID(self):
        return self.uid

    # Devuelve una lista con las banderas activas del mensaje.
    def getFlags(self):
        flags = []
        return flags

    # Devuelve la fecha interna del mensaje en formato RFC.
    def getInternalDate(self):
        return email.utils.formatdate()

    # Devuelve únicamente los encabezados del mensaje.
    # Separa los encabezados del cuerpo usando la doble línea en blanco.
    def getRFC822Headers(self):
        headers, _, _ = self.content.partition("\n\n")
        return headers

    # Devuelve el mensaje completo en formato RFC822.
    def getRFC822Text(self):
        return self.content

    # Devuelve el tamaño del mensaje (en bytes, codificado en UTF-8).
    def getSize(self):

        return len(self.content.encode("utf-8"))

    # Indica si el mensaje es multipart
    def isMultipart(self):

        return False

    # Devuelve un objeto BytesIO con el contenido completo del mensaje.
    def getBodyFile(self):

        return BytesIO(self.getRFC822Text().encode("utf-8"))

    # Devuelve un diccionario con los encabezados filtrados.
    # Si se especifican campos, se devuelven (o se excluyen si 'negate' es True) según la lista.
    def getHeaders(self, negate, *fields):
        parser = HeaderParser()
        headers_str = self.getRFC822Headers()
        msg = parser.parsestr(headers_str)
        headers_dict = dict(msg.items())
        if fields:

            fields_lower = [f.decode("utf-8").lower() if isinstance(f, bytes) else f.lower() for f in fields]
            if not negate:

                headers_dict = {k: v for k, v in headers_dict.items() if k.lower() in fields_lower}
            else:

                headers_dict = {k: v for k, v in headers_dict.items() if k.lower() not in fields_lower}
        return headers_dict

#Clase de excepcion cuando no se encuientra el mensaje solicitado
class NoSuchMessage(imap4.MailboxException):
    def __init__(self, num):
        super().__init__("No such message: %s" % num)

# Contenedor de los datos recuperados de un mensaje
class FetchResult(list):
    # Constructor:
    # message: instancia de mensaje SimpleMessage
    def __init__(self, message, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.message = message

    # Métodos de acceso que delegan en la instancia de mensaje:
    def getFlags(self):
        return self.message.getFlags()

    def getUID(self):
        return self.message.getUID()

    def getSize(self):
        return self.message.getSize()

    def getHeaders(self, negate, *fields):
        return self.message.getHeaders(negate, *fields)

    def isMultipart(self):
        return self.message.isMultipart()

    def getBodyFile(self):
        return self.message.getBodyFile()


#Clase que representa un buzón de correo basado en un directorio en disco.
@implementer(imap4.IMailbox)
class DiskMailbox:
    def __init__(self, path):
        # Constructor:
        # path: ruta del directorio donde se almacenan los mensajes (archivo.eml)
        self.path = path
        if not os.path.isdir(path):
            raise Exception("El buzón de correo no existe: {}".format(path))
        self.refresh()

    # Actualiza la lista de mensajes leyendo el directorio.
    def refresh(self):
        self.messages = []
        for f in sorted(os.listdir(self.path)):
            file_path = os.path.join(self.path, f)
            if os.path.isfile(file_path):
                self.messages.append(file_path)
        self.uidValidity = 1

    # Devuelve un rango de números de mensaje, basado en la cantidad de archivos.
    def listMessages(self):
        self.refresh()
        return range(1, len(self.messages) + 1)

    # Devuelve un mensaje (instancia de SimpleMessage) dado su número.
    def getMessage(self, num):
        if 1 <= num <= len(self.messages):
            file_path = self.messages[num - 1]
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception:
                return defer.fail(NoSuchMessage(num))
            message = SimpleMessage(content, uid=num)
            return defer.succeed(message)
        else:
            return defer.fail(NoSuchMessage(num))

    # Método para obtener mensajes en bloque.
    # messages: lista de números de mensajes o un objeto iterable.
    # uid: si se solicita el UID
    def fetch(self, messages, uid=False):
        results = {}
        deferreds = []
        try:
            msg_nums = list(messages)
        except TypeError as e:
            if "last value not set" in str(e):
                start = getattr(messages, "first", 1)
                msg_nums = list(range(start, self.getMessageCount() + 1))
            else:
                raise

        for msgnum in msg_nums:
            d = self.getMessage(msgnum)

            def add_result(msg, msgnum=msgnum):
                flags = msg.getFlags()
                if flags:
                    flags_bytes = b'(' + b' '.join(flag.encode("utf-8") for flag in flags) + b')'
                else:
                    flags_bytes = b'()'
                return FetchResult(msg, [(b"FLAGS", flags_bytes), (b"RFC822", msg.getRFC822Text().encode("utf-8"))])

            d.addCallback(add_result)
            d.addCallback(lambda result, msgnum=msgnum: results.__setitem__(msgnum, result))
            deferreds.append(d)
        return defer.DeferredList(deferreds).addCallback(lambda _: list(results.items()))

    # Proporciona el estado del buzón en base a los nombres solicitados.
    def requestStatus(self, names):

        result = {}
        for name in names:
            upperName = name.upper()
            if upperName == b"MESSAGES":
                result[b"MESSAGES"] = self.getMessageCount()
            elif upperName == b"RECENT":
                result[b"RECENT"] = self.getRecentCount()
            elif upperName == b"UIDNEXT":
                result[b"UIDNEXT"] = self.getUIDNext()
            elif upperName == b"UIDVALIDITY":
                result[b"UIDVALIDITY"] = self.getUIDValidity()
            elif upperName == b"UNSEEN":

                result[b"UNSEEN"] = 0

        return defer.succeed(result)

    # Métodos auxiliares para obtener información del buzón.
    def getMessageCount(self):
        self.refresh()
        return len(self.messages)

    def getUIDValidity(self):
        return self.uidValidity

    def getUIDNext(self):
        return self.uidValidity + len(self.messages) + 1

    def getFlags(self):
        return []

    def getHierarchicalDelimiter(self):
        return "/"

    def getRecentCount(self):
        return 0

    def isWriteable(self):
        return True

    def addListener(self, listener):

        pass

# Clase que representa una cuenta de usuario basada en un buzón de correo almacenado en disco.
@implementer(imap4.IAccount)
class DiskAccount:
    def __init__(self, username, mail_storage):
        # Constructor:
        # username: dirección de correo del usuario (formato usuario@dominio)
        # mail_storage: ruta base donde se almacenan los buzones
        if '@' not in username:
            raise Exception("El nombre de usuario debe tener formato usuario@dominio")
        local, domain = username.split('@', 1)
        mailbox_path = os.path.join(mail_storage, domain, local)
        self.inbox = DiskMailbox(mailbox_path)

    # Devuelve la lista de buzones; en este ejemplo solo se maneja "INBOX".
    def listMailboxes(self, subscribedOnly=False, pattern='*'):

        if pattern in ('*', 'INBOX'):
            return defer.succeed([("INBOX", self.inbox)])
        else:
            return defer.succeed([])

    # Selecciona un buzón para acceder a sus mensajes.
    def select(self, mailbox, readonly=False):
        if mailbox.upper() == "INBOX":
            return defer.succeed(self.inbox)
        else:
            return defer.fail(imap4.MailboxException("No existe el buzón solicitado: {}".format(mailbox)))

    # Métodos para crear, eliminar o renombrar buzones.
    def create(self, name):

        if name.upper() == "INBOX":
            return defer.succeed(self.inbox)
        else:
            return defer.succeed(None)

    def delete(self, name):
        return defer.fail(imap4.MailboxException("No se permite eliminar buzones."))

    def rename(self, oldName, newName):
        return defer.fail(imap4.MailboxException("No se permite renombrar buzones."))

    def subscribe(self, name):

        return defer.succeed(None)

    def unsubscribe(self, name):

        return defer.succeed(None)

    def isSubscribed(self, mailboxName):

        return mailboxName.upper() == "INBOX"


# Clase que define el entorno de autenticación y acceso a las cuentas de correo,
# permitiendo que los usuarios autenticados accedan a su buzón de forma segura.
@implementer(portal.IRealm)
class DiskIMAPRealm:
    # Constructor:
    # mail_storage: ruta base donde se almacenan los buzones de correo
    def __init__(self, mail_storage):
        self.mail_storage = mail_storage

    # Solicita el "avatar" para la autenticación.
    # Si se solicita la interfaz imap4.IAccount, se crea una instancia de DiskAccount.
    def requestAvatar(self, avatarId, mind, *interfaces):
        if imap4.IAccount in interfaces:

            username = avatarId.decode('utf-8') if isinstance(avatarId, bytes) else avatarId
            try:
                account = DiskAccount(username, self.mail_storage)
            except Exception as e:
                return defer.fail(e)
            return imap4.IAccount, account, lambda: None
        raise NotImplementedError()


# Clase que se encarga de autenticar a los usuarios consultando un archivo CSV
@implementer(checkers.ICredentialsChecker)
class CSVChecker:
    # Define que este checker maneja credenciales de usuario/contraseña.
    credentialInterfaces = (credentials.IUsernamePassword,)

    # Constructor:
    # csv_path: ruta del archivo CSV que contiene las credenciales de los usuarios.
    def __init__(self, csv_path):
        self.users = {}
        with open(csv_path, newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:

                email_addr = row['email'].strip()
                passwd = row['password'].strip()
                self.users[email_addr] = passwd

    # Método que verifica las credenciales proporcionadas.
    def requestAvatarId(self, creds):

        username = creds.username.decode('utf-8') if isinstance(creds.username, bytes) else creds.username
        password = creds.password.decode('utf-8') if isinstance(creds.password, bytes) else creds.password
        if username in self.users and self.users[username] == password:
            return defer.succeed(username)
        return defer.fail(credError.UnauthorizedLogin("Usuario o contraseña inválidos"))



# Clase que centraliza la creación de servidores IMAP,
# asegurando que cada conexión utilice la misma configuración y mecanismos de autenticación.
class IMAPFactory(protocol.Factory):
    # Constructor:
    # portal: instancia de portal.Portal que se utiliza para la autenticación y obtención de cuentas.
    def __init__(self, portal):
        self.portal = portal

    # Método para construir el protocolo IMAP4Server para cada conexión entrante.
    def buildProtocol(self, addr):
        server = imap4.IMAP4Server()
        server.portal = self.portal
        server.challengers = {
            b"LOGIN": imap4.LOGINCredentials,
            b"PLAIN": imap4.PLAINCredentials,
        }
        return server



CSV_PATH = "/home/ec2-user/Tarea1_redes/credentials.csv"

# Funcion principal que construye el servidor IMAP
def main():
    parser = argparse.ArgumentParser(
        description="Servidor IMAP que utiliza el mail storage del servidor SMTP.\nEstructura: <mail-storage>/<dominio>/<usuario>/archivo.eml"
    )
    parser.add_argument("-s", "--mail-storage", required=True, help="Ruta base para los buzones")
    parser.add_argument("-p", "--port", type=int, default=143, help="Puerto IMAP (default: 143)")
    args = parser.parse_args()


    realm = DiskIMAPRealm(args.mail_storage)

    p = portal.Portal(realm, [CSVChecker(CSV_PATH)])
    factory = IMAPFactory(p)
    reactor.listenTCP(args.port, factory)
    print(f"Servidor IMAP escuchando en el puerto {args.port}")
    reactor.run()


if __name__ == '__main__':
    main()
