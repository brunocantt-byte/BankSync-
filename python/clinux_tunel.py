from __future__ import annotations

from contextlib import closing
import select
import socket
import socketserver
import threading

import paramiko


TUNEIS_ATIVOS = []


def porta_livre(host="127.0.0.1"):
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


class Encaminhador(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            canal = self.ssh_transport.open_channel(
                "direct-tcpip",
                (self.remote_host, self.remote_port),
                self.request.getpeername(),
            )
        except Exception:
            return

        if canal is None:
            return

        while True:
            leitura, _, _ = select.select([self.request, canal], [], [], 1)

            if self.request in leitura:
                dados = self.request.recv(65535)
                if not dados:
                    break
                canal.sendall(dados)

            if canal in leitura:
                dados = canal.recv(65535)
                if not dados:
                    break
                self.request.sendall(dados)

        canal.close()
        self.request.close()


class ServidorTunel(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class TunelClinux:
    def __init__(
        self,
        *,
        ssh_host,
        ssh_port,
        ssh_user,
        ssh_password,
        ssh_key_path=None,
        remote_host,
        remote_port,
        local_port=None,
    ):
        self.ssh_host = ssh_host
        self.ssh_port = int(ssh_port)
        self.ssh_user = ssh_user
        self.ssh_password = ssh_password
        self.ssh_key_path = ssh_key_path
        self.remote_host = remote_host
        self.remote_port = int(remote_port)
        self.local_host = "127.0.0.1"
        self.local_port = int(local_port) if local_port else porta_livre()
        self.client = None
        self.server = None
        self.thread = None

    def abrir(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            self.ssh_host,
            port=self.ssh_port,
            username=self.ssh_user,
            password=self.ssh_password or None,
            key_filename=self.ssh_key_path or None,
            timeout=12,
            banner_timeout=12,
            auth_timeout=12,
            look_for_keys=False,
            allow_agent=False,
        )

        transporte = client.get_transport()

        class Handler(Encaminhador):
            remote_host = self.remote_host
            remote_port = self.remote_port
            ssh_transport = transporte

        server = ServidorTunel((self.local_host, self.local_port), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        self.client = client
        self.server = server
        self.thread = thread
        TUNEIS_ATIVOS.append(self)
        return self

    def fechar(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()

        if self.client:
            self.client.close()


def abrir_tunel_proprio(config):
    if config.get("ssh_key_path"):
        try:
            tunel = TunelClinux(
                ssh_host=config["ssh_host"],
                ssh_port=config["ssh_port"],
                ssh_user=config["ssh_user"],
                ssh_password=None,
                ssh_key_path=config["ssh_key_path"],
                remote_host=config["host"],
                remote_port=config["port"],
            ).abrir()
            return "SSH_KEY", tunel
        except Exception as erro:
            erros = [f"SSH_KEY: {type(erro).__name__}"]
    else:
        erros = []

    senhas = [
        ("SSHPASS", config.get("ssh_password")),
        ("SSHPASSX", config.get("ssh_password_alt")),
    ]

    for label, senha in senhas:
        if not senha:
            continue

        try:
            tunel = TunelClinux(
                ssh_host=config["ssh_host"],
                ssh_port=config["ssh_port"],
                ssh_user=config["ssh_user"],
                ssh_password=senha,
                remote_host=config["host"],
                remote_port=config["port"],
            ).abrir()
            return label, tunel
        except Exception as erro:
            erros.append(f"{label}: {type(erro).__name__}")

    raise ConnectionError(
        "Nao foi possivel abrir tunel SSH proprio. Tentativas: "
        + ", ".join(erros)
    )
