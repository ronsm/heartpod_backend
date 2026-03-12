from multiprocessing.connection import Client
from sys import exit
from time import sleep


ADDRESS = (HOST, PORT) = ("localhost", 61000)
"""Hostname/IP address and TCP port where the STT server listens."""


RETRY_INTERVAL = 3
"""Time in seconds between connection attempts to the STT server."""


START = "Start STT"
"""Client command to request the server start listening to the user."""


STOP = "Stop STT"
"""Client command to request the server stop listening to the user."""


try:
    while True:
        try:
            print(f"Trying to connect to STT server at {ADDRESS}")
            with Client(ADDRESS) as connection:
                print(f"Connected to {ADDRESS}")

                # Tell speech-to-text server to start listening to the user
                connection.send(START)
                print(f"Request sent: {START}")

                while True:
                    try:
                        # The next line blocks until there is something to receive
                        msg = connection.recv()

                    except EOFError:
                        # There is nothing left to receive and the other end was closed
                        print("Connection closed by the server")
                        raise

                    except KeyboardInterrupt:
                        # The user hit Ctrl+C
                        break

                    else:
                        print(f"Received from server: {msg}")

                # Tell speech-to-text server to stop listening to the user
                connection.send(STOP)
                print(f"Request sent: {STOP}")

                # Successive START/STOP commands can be sent on the same connection,
                # for instance here is a second START/STOP session, used to pull a
                # single message from the socket:
                # connection.send(START)
                # print(f"Request sent: {START}")
                # print(f"Received from server: {connection.recv()}")
                # connection.send(STOP)
                # print(f"Request sent: {STOP}")

            print("Connection closed")
            break

        except ConnectionRefusedError:
            # No speech-to-text server is running at the specified address
            print(f"No STT server at {ADDRESS}, retrying in {RETRY_INTERVAL} seconds")
            sleep(RETRY_INTERVAL)

        except EOFError:
            # Connection closed by the server
            print(f"Retrying in {RETRY_INTERVAL} seconds")
            sleep(RETRY_INTERVAL)

except KeyboardInterrupt:
    # The user hit Ctrl+C
    pass
