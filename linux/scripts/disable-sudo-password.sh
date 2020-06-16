#!/bin/bash

sudo usermod -aG sudo $(whoami)

sudo mkdir -p /etc/sudoers.d

sudo sh -c "sudo echo \"%sudo ALL=(ALL) NOPASSWD:ALL\" > /etc/sudoers.d/sudo"