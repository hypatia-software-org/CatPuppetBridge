# This file is part of CatPuppetBridge.
#
# CatPuppetBridge is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.
#
# CatPuppetBridge is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# CatPuppetBridge. If not, see <https://www.gnu.org/licenses/>.
#
# Copyright (C) 2025 Lisa Marie Maginnis

PROGRAM := catpuppetbridge
VERSION := $(shell dpkg-parsechangelog --show-field Version 2>/dev/null)
TAG := v$(VERSION)
PREFIX := '/usr/local'

DEB_FILE := ../$(PROGRAM)_$(VERSION)_all.deb
SIG_FILE := $(DEB_FILE).sig

lint:
	pylint --rcfile=.pylintrc src/main.py src/modules
test:
	pytest -v --timeout=10
build-pypi:
	python3 -m build
clean:
	rm -f dist/*
release:
	git checkout main
	git pull origin main
	git tag $(TAG)
	git push tag $(TAG)
debian-pkg:
	dpkg-buildpackage -us -uc -d
debian-sign: debian-pkg
	gpg --output $(SIG_FILE) --detach-sign $(DEB_FILE)
debian-upload: debian-sign
	gh release upload $(TAG) $(DEB_FILE) $(SIG_FILE) --clobbe
install:
	mkdir -p $(PREFIX)/lib/catpuppetbridge
	cp -r src/* $(PREFIX)/lib/catpuppetbridge
	ln -fs $(PREFIX)/lib/catpuppetbridge/main.py $(PREFIX)/bin/catpuppetbridge
	chmod 555 $(PREFIX)/bin/catpuppetbridge
	cp -n catbridge.ini.default /etc/catbridge.ini
install-venv: install install-systemd
	virtualenv $(PREFIX)/lib/catpuppetbridge/venv
	sed "s_ExecStart=$(PRFIX)/bin_ExecStart=/usr/local/lib/catpuppetbridge/venv _" -i /etc/systemd/system/catpuppetbridge.service
	systemctl daemon-reload
install-systemd:
	cp debian/catpuppetbridge.service /etc/systemd/system/
	sed "s_PREFIX_$(PREFIX)_" -i /etc/systemd/system/catpuppetbridge.service
	systemctl daemon-reload
install-user:
	adduser --system --group --home $(PREFIX)/lib/catpuppetbridge --disabled-login --shell /usr/sbin/nologin catpuppet
uninstall:
	rm -rf $(PREFIX)/lib/catpuppetbridge
	rm -f $(PREFIX)/bin/catpuppetbridge
	rm -f /etc/catbridge.ini
	rm -f /etc/systemd/system/catpuppetbridge.service
	systemctl daemon-reload
