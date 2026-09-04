{
  description = "iaclens: an infrastructure knowledge-graph MCP server for Terraform, Kubernetes, ArgoCD, Helm, and Kustomize";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    {
      overlays.default = final: _prev: {
        iaclens = final.python3Packages.callPackage ./nix/package.nix { };
      };
    }
    // flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          overlays = [ self.overlays.default ];
        };
      in
      {
        packages.default = pkgs.iaclens;
        packages.iaclens = pkgs.iaclens;

        apps.default = {
          type = "app";
          program = "${pkgs.iaclens}/bin/iaclens";
          meta.description = "iaclens CLI";
        };

        devShells.default = pkgs.mkShell {
          inputsFrom = [ pkgs.iaclens ];
          packages = with pkgs.python3Packages; [ pytest pytest-cov ruff mypy ];
        };
      });
}
