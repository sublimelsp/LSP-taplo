# LSP-taplo

TOML support for Sublime Text's LSP plugin.

Uses [Taplo Language Server](https://taplo.tamasfe.dev/)
to provide completions, validation, formatting and other features for TOML files.
See linked site for more information.

## Installation

1. Install [LSP](https://packagecontrol.io/packages/LSP) and [LSP-taplo](https://packagecontrol.io/Packages/LSP-taplo) from Package Control.
2. Restart Sublime Text.

> [!NOTE]
>
> The plugin does not distribute but download language server binaries from official sources.

## Configuration

Open configuration file 
by running `Preferences: LSP-taplo Settings` from Command Palette 
or via Main Menu (`Preferences > Package Settings > LSP > Servers > LSP-taplo`).

Taplo supports [`.taplo.toml` and `taplo.toml`](https://taplo.tamasfe.dev/configuration/file.html) files 
to manage folder specific configuration.

## Usage

> [!NOTE]
>
> The following commands require a TOML file to be focused.

### Assigning Schemas

Document validation and completions require proper JSON schema 
to be assigned to a document.

JSON schemas can by assigned dynamically by calling `Taplo: Select schema for TOML`.

### Copy & Paste

To convert copied content between JSON and TOML,
open _Command Palette_ and type:

- `Edit: Copy as JSON`
- `Edit: Paste as JSON`
- `Edit: Paste as TOML`
