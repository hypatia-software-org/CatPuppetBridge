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


lint:
	pylint --rcfile=.pylintrc main.py modules
test:
	pytest -v --timeout=10
