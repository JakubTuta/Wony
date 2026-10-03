#!/bin/sh
# Runs Wony with whichever Python this device has.
#
#   ./wony.sh                   start Wony (the screen and everything behind it)
#   ./wony.sh text              type to Wony in a terminal
#   ./wony.sh doctor            check the setup and exit
#   ./wony.sh autostart install start Wony at boot
#   ./wony.sh setup             install, or add a feature
#   ./wony.sh setup configure   add a key or sign in again

cd "$(dirname "$0")" || exit 1

# The project's own venv first, then `python`, then `python3`: Raspberry Pi OS
# ships only python3 unless python-is-python3 is installed.
python=""
too_old=""
for candidate in venv/bin/python python python3; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
        python=$candidate
        break
    fi
    too_old=$candidate
done

if [ -z "$python" ]; then
    echo
    if [ -n "$too_old" ]; then
        echo "  The Python on this device is too old: Wony needs Python 3.10 or newer."
    else
        echo "  Python is not installed on this device (looked for python and python3)."
    fi
    echo "  Install it, then run this again:"
    echo
    echo "    sudo apt install python3 python3-venv"
    echo
    exit 1
fi

if [ "$1" = "setup" ]; then
    shift
    exec "$python" setup.py "$@"
fi
exec "$python" wony.py "$@"
