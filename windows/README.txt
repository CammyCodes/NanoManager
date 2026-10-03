NanoManager for Windows
=======================

Double-click "Start NanoManager.bat". A window opens with the control page; the black console
window is the server, so leave it open (minimised is fine) and close it to stop NanoManager.

Want to use it from your phone too? Start "Start NanoManager (phone access).bat" instead. Windows
will ask to allow it through the firewall: choose "Private networks". The console shows the
address to open on your phone.

First time: it finds your Nanoleaf on the network and shows how to pair (hold the controller's
power button for 5-7 seconds until the lights flash).

Your pairing and saved scenes live in %APPDATA%\NanoManager. Delete that folder to start fresh.
There is nothing to install: this folder carries its own Python. To remove NanoManager, delete
this folder (and the shortcuts, if you made any).

If Windows SmartScreen says "Windows protected your PC", choose More info > Run anyway: the
program is unsigned because it is a free hobby project. The full source is on GitHub.

Project page and help: https://github.com/CammyCodes/NanoManager
