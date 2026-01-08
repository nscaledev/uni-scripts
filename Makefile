# Could change it to /usr/local/bin or something, but run as sudo.
PREFIX := $(HOME)/bin

# Add binaries here to have them installed.
BINARIES := build \
	    deploy \
	    restart \
	    ui-preview \
	    clean-images

.PHONY: install
install: $(BINARIES)
	mkdir -p $(PREFIX)
	for binary in $(BINARIES); do install -m 0755 $${binary} $(PREFIX); done
