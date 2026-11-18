# A bootable NixOS system that exercises the module against real GCP.
#
# Wire it up through the flake so `services.python-tofu.package` points at this
# checkout:
#
#   nix build .#nixosConfigurations.tofu-live.config.system.build.vm
#   ./scripts/live-module-vm.sh
#
# Booting this system is the same code path as `nixos-rebuild switch`: the
# Nix-declared stack is evaluated at build time into `python-tofu-stack.json`,
# becomes a `restartTriggers` input, and `python-tofu.service` runs the real
# `apply` under the module's systemd sandbox. There is no stub binary and no
# mocked `tofu`.
#
# Two host directories are shared over 9p:
#
#   /run/agenix  ← a temporary 0400 copy of the agenix credential, removed when
#                  the harness exits. The real agenix directory is
#                  `drwxr-x--x root:keys`, which QEMU cannot open as a 9p
#                  source, and the secret must never be copied into the store.
#   /mnt/workdir ← the caller's workdir, so the rendered HCL and the state file
#                  survive the VM and `destroy` can clean up afterwards
{ pkgs, ... }:
{
  system.stateVersion = "24.11";

  # This system is only booted as a VM (direct kernel boot), so it needs no boot
  # loader. `nix flake check` still evaluates the base configuration and NixOS
  # asserts a root filesystem, so declare the generic image layout the VM
  # variant would otherwise supply itself.
  fileSystems."/" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "ext4";
  };
  boot.loader.grub.enable = false;

  networking.hostName = "python-tofu-live";
  # QEMU user-mode networking: outbound only, enough for the GCP APIs.
  networking.useDHCP = true;

  # Serial console instead of a window, so the harness can capture it.
  # VM-only options live in `vmVariant`; `system.build.vm` extends the base
  # configuration with them.
  virtualisation.vmVariant = {
    virtualisation.graphics = false;
    virtualisation.memorySize = 2048;
    virtualisation.cores = 2;

    virtualisation.sharedDirectories = {
      agenix = {
        # A 0400 copy prepared by scripts/live-module-vm.sh; see the header.
        source = ''"''${LIVE_VM_CRED_DIR}"'';
        target = "/run/agenix";
        securityModel = "none";
      };
      workdir = {
        # Expanded by the VM run script (qemu-vm.nix allows a shell expression).
        source = ''"''${LIVE_VM_WORKDIR}"'';
        target = "/mnt/workdir";
        securityModel = "none";
      };
    };

    # The unit is a boot-time oneshot, so a VM would otherwise run forever.
    # Record the result on the serial console (the harness greps for it) and
    # power off. `after` alone, without `requires`, means a failed apply still
    # reaches here.
    systemd.services.live-vm-done = {
      wantedBy = [ "multi-user.target" ];
      after = [ "python-tofu.service" ];
      path = [ pkgs.systemd ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
        journalctl -u python-tofu.service --no-pager -n 120 > /dev/ttyS0 || true
        echo "LIVE-VM result=$(systemctl show -p Result --value python-tofu.service) state=$(systemctl show -p ActiveState --value python-tofu.service)" > /dev/ttyS0
        sleep 1
        systemctl poweroff
      '';
    };
  };

  services.python-tofu = {
    enable = true;

    # The mirrored provider keeps `tofu init` off the public registry.
    tofuPackage = pkgs.opentofu.withPlugins (plugins: [ plugins.hashicorp_google ]);

    # Evaluate at build time, exactly like a rebuild-time stack declaration.
    stackFile = ./live-vm-stack.nix;

    settings = {
      command = "apply";
      autoApprove = true;
      workdir = "/mnt/workdir";
    };
  };

  # Keep the apply output on the serial console so a failed run is diagnosable
  # from the harness log alone.
  systemd.services.python-tofu.serviceConfig.StandardOutput = "journal+console";
  systemd.services.python-tofu.serviceConfig.StandardError = "journal+console";
}
