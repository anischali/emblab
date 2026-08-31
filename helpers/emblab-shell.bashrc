# Passed to `bash --rcfile` by containers.py's shell() — NOT auto-sourced.
#
# Interactive bash normally sources ~/.bashrc, but `emblab shell` runs as
# the host user borrowed via udocker's --hostauth (see shell()'s docstring)
# with no real $HOME inside the container, so there is no ~/.bashrc to find
# system Debian's own bash-completion sourcing block, which normally lives
# there (from /etc/skel/.bashrc), not in the system-wide /etc/bash.bashrc —
# confirmed against a real provisioned container: without this, `shopt
# progcomp` was already on (bash's own default) but no completion function
# was actually registered for e.g. apt-get. This file does that sourcing
# itself, from a fixed path (bind-mounted onto HELPERS_MOUNT, on PATH via
# every containers.run()/shell() call) instead of depending on $HOME.
[ -f /etc/bash.bashrc ] && . /etc/bash.bashrc

if ! shopt -oq posix; then
	if [ -f /usr/share/bash-completion/bash_completion ]; then
		. /usr/share/bash-completion/bash_completion
	elif [ -f /etc/bash_completion ]; then
		. /etc/bash_completion
	fi
fi

PS1='[emblab] \u:\w\$ '
