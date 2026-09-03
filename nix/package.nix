# nix/package.nix
{ lib
, buildPythonApplication
, hatchling
, networkx
, python-hcl2
, ruamel-yaml
, click
, mcp
, pathspec
, watchdog
}:

buildPythonApplication {
  pname = "iaclens";
  version = "0.5.0";  # keep in sync with pyproject.toml
  pyproject = true;
  src = lib.cleanSource ../.;

  build-system = [ hatchling ];

  dependencies = [
    networkx
    python-hcl2
    ruamel-yaml
    click
    mcp
    pathspec
    watchdog
  ];

  # The upstream test suite is not part of the runtime closure; run tests in the devShell.
  doCheck = false;

  meta = {
    description = "Infrastructure knowledge-graph MCP server for IaC files";
    homepage = "https://github.com/ScrimReaper/iaclens";
    license = lib.licenses.asl20;
    mainProgram = "iaclens";
  };
}
