# nix/package.nix
{ lib
, buildPythonApplication
, installShellFiles
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
  version = "0.7.1";  # keep in sync with pyproject.toml
  pyproject = true;
  src = lib.cleanSource ../.;

  build-system = [ hatchling ];

  nativeBuildInputs = [ installShellFiles ];

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

  # Ship bash/zsh/fish completions so any shell completes commands, options, and
  # node ids out of the box. The built binary emits each script.
  postInstall = ''
    installShellCompletion --cmd iaclens \
      --bash <($out/bin/iaclens completion bash) \
      --zsh <($out/bin/iaclens completion zsh) \
      --fish <($out/bin/iaclens completion fish)
  '';

  meta = {
    description = "Infrastructure knowledge-graph MCP server for IaC files";
    homepage = "https://github.com/ScrimReaper/iaclens";
    license = lib.licenses.asl20;
    mainProgram = "iaclens";
  };
}
