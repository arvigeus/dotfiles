#!/bin/bash

sudo apt-get remove --purge libreoffice*
sudo apt-get clean
sudo apt-get autoremove

flatpak install flathub org.onlyoffice.desktopeditors