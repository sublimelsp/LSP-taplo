from __future__ import annotations
import gzip
import json
import os
import time

from functools import partial
from typing import cast
from urllib.request import urlopen

import sublime

from LSP.plugin import (
    AbstractPlugin,
    ClientConfig,
    LspTextCommand,
    Notification,
    Request,
    Session,
    WorkspaceFolder,
    register_plugin,
    unregister_plugin,
    uri_from_view,
)
from LSP.plugin.core.views import (
    extract_variables,
)

__all__ = [
    "TaploAssignSchemaCommand",
    "TaploCopyAsJsonCommand",
    "TaploPasteAsJsonCommand",
    "TaploPasteAsTomlCommand",
    "TaploPlugin",
    "plugin_loaded",
    "plugin_unloaded",
]


class TaploPlugin(AbstractPlugin):
    package_name: str = __spec__.parent
    server_version: str = ""

    # LSP API methods

    @classmethod
    def name(cls):
        return "LSP-taplo"

    @classmethod
    def configuration(cls):
        settings_file_name = "LSP-taplo.sublime-settings"
        return (
            sublime.load_settings(settings_file_name),
            f"Packages/{cls.package_name}/{settings_file_name}",
        )

    @classmethod
    def needs_update_or_installation(cls):
        server_file = cls.server_file()
        is_upgrade = os.path.isfile(server_file)
        if is_upgrade:
            next_update_check, server_version = cls.load_metadata()
        else:
            next_update_check, server_version = 0, ""

        settings, _ = cls.configuration()
        cls.server_version = str(settings.get("server_version", "latest"))
        if cls.server_version == "latest":
            if int(time.time()) >= next_update_check:
                try:
                    # response url ends with latest available version number
                    url = "https://github.com/tamasfe/taplo/releases/latest"
                    available_version = urlopen(url).url.rsplit("/", 1)[1]
                    if available_version != server_version:
                        cls.server_version = available_version
                        return True
                except BaseException:
                    cls.save_metadata(False, server_version)

            return False

        return cls.server_version != server_version

    @classmethod
    def install_or_update(cls):
        if not cls.server_version:
            raise RuntimeError()

        os.makedirs(cls.server_path(), exist_ok=True)

        # downlad and ungzip server binary (ignore any other files)
        response = urlopen(cls.make_url(cls.server_version))
        server_file = cls.server_file()
        with gzip.GzipFile(fileobj=response) as arc, open(server_file, "wb") as out:
            out.write(arc.read())

        os.chmod(server_file, 0o755)

        # write update cookie
        cls.save_metadata(True, cls.server_version)

    @classmethod
    def on_pre_start(
        cls,
        window: sublime.Window,
        initiating_view: sublime.View,
        workspace_folders: list[WorkspaceFolder],
        configuration: ClientConfig,
    ) -> str | None:
        # ensure configured cache path exists, as taplo doesn't do that itself.
        variables = extract_variables(window)
        variables.update(cls.additional_variables())
        cache_path = os.path.normpath(configuration.init_options.get("cachePath"))
        cache_path = cast(str, sublime.expand_variables(cache_path, variables))
        os.makedirs(cache_path, exist_ok=True)

    @classmethod
    def additional_variables(cls) -> dict[str, str]:
        return {"server_file": cls.server_file(), "server_path": cls.server_path()}

    # server specific methods

    @classmethod
    def cleanup(cls):
        def run_async() -> None:
            from shutil import rmtree

            server_path = cls.server_path()
            # Enable long path support on on Windows
            # see: https://stackoverflow.com/a/14076169/4643765
            # see: https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation
            if sublime.platform() == "windows":
                server_path = Rf"\\?\{server_path}"

            if os.path.isdir(server_path):
                rmtree(server_path, ignore_errors=True)

        try:
            from package_control import events  # type: ignore

            if events.remove(cls.package_name):
                sublime.set_timeout_async(run_async, 1000)
        except ImportError:
            pass  # Package Control is not required.

    @staticmethod
    def make_url(version: str) -> str:
        asset = {
            "linux-arm64": "taplo-linux-aarch64.gz",
            "linux-x32": "taplo-linux-x86.gz",
            "linux-x64": "taplo-linux-x86_64.gz",
            "osx-arm64": "taplo-darwin-aarch64.gz",
            "osx-x64": "taplo-darwin-x86_64.gz",
            "windows-arm64": "taplo-windows-aarch64.gz",
            "windows-x32": "taplo-windows-x86.gz",
            "windows-x64": "taplo-windows-x86_64.gz",
        }[f"{sublime.platform()}-{sublime.arch()}"]
        return f"https://github.com/tamasfe/taplo/releases/download/{version}/{asset}"

    @classmethod
    def server_file(cls) -> str:
        name = os.path.join(cls.server_path(), "taplo")
        if sublime.platform() == "windows":
            name += ".exe"
        return name

    @classmethod
    def server_path(cls) -> str:
        return os.path.join(cls.storage_path(), cls.package_name)

    @classmethod
    def metadata_file(cls) -> str:
        return os.path.join(cls.server_path(), "update.json")

    @classmethod
    def load_metadata(cls) -> tuple[int, str]:
        try:
            with open(cls.metadata_file()) as fobj:
                data = json.load(fobj)
                return int(data["timestamp"]), data["version"]
        except (FileNotFoundError, KeyError, TypeError, ValueError):
            return 0, ""

    @classmethod
    def save_metadata(cls, success: bool, version: str) -> None:
        next_run_delay = (7 * 24 * 60 * 60) if success else (6 * 60 * 60)
        with open(cls.metadata_file(), "w") as fobj:
            json.dump(
                {
                    "timestamp": int(time.time()) + next_run_delay,
                    "version": version,
                },
                fp=fobj,
            )


class TaploAssignSchemaCommand(LspTextCommand):
    """
    This class implements the `taplo_assign_schema` command.

    The command requests a list of available JSON schemas from taplo language server
    and presents them in a quick panel. Selected schema is assigned to open document.
    """

    session_name = TaploPlugin.name()

    def run(self, _: sublime.Edit):
        session = self.session_by_name()
        if session:
            session.send_request(
                request=Request(
                    method="taplo/listSchemas",
                    params={"documentUri": uri_from_view(self.view)},
                    view=self.view,
                ),
                on_result=partial(self.prompt, session),
            )

    def prompt(self, session: Session, response: dict) -> None:
        window = self.view.window()
        if window:
            window.show_quick_panel(
                items=[
                    sublime.QuickPanelItem(
                        trigger=schema["meta"]["name"],
                        annotation=schema["meta"]["source"],
                        details=schema["meta"]["description"],
                    )
                    for schema in response["schemas"]
                ],
                on_select=partial(self.apply, session, response["schemas"]),
            )

    def apply(self, session: Session, schemas: dict, index: int) -> None:
        if index >= 0:
            document_uri = uri_from_view(self.view)
            schema = schemas[index]
            session.send_notification(
                Notification(
                    method="taplo/associateSchema",
                    params={
                        "documentUri": document_uri,
                        "schemaUri": schema["url"],
                        "rule": {"url": document_uri},
                        "meta": schema["meta"],
                    },
                )
            )


class TaploCopyAsJsonCommand(LspTextCommand):
    """
    This class implements the `taplo_copy_as_json` command.

    The command copies selected TOML content to clipboard as JSON.
    """

    session_name = TaploPlugin.name()

    def run(self, _: sublime.Edit) -> None:
        text = ""
        sels = self.view.sel()
        if sels:
            for sel in sels:
                if not sel.empty():
                    text += self.view.substr(sel)

        if not text:
            sel = sublime.Region(0, self.view.size())
            text = self.view.substr(sel)

        if not text:
            window = self.view.window()
            if window:
                window.status_message("No text to copy!")
            return

        session = self.session_by_name()
        if not session:
            window = self.view.window()
            if window:
                window.status_message("No language server session!")
            return

        session.send_request(
            request=Request(
                method="taplo/convertToJson",
                params={"text": text},
                view=self.view,
            ),
            on_result=self.set_clipboard,
        )

    def set_clipboard(self, response: dict[str, str]) -> None:
        error = response.get("error")
        if error:
            sublime.error_message(f"Failed to convert to JSON:\n\n{error}")
            return

        text = response.get("text")
        if not text:
            sublime.error_message("Converted content is empty, but it shouldn't!")
            return

        sublime.set_clipboard(text)


class TaploPasteAsJsonCommand(LspTextCommand):
    """
    This class implements the `taplo_paste_as_json` command.

    The command inserts TOML clipboard content at caret location(s) as JSON.
    """

    session_name = TaploPlugin.name()

    def run(self, _: sublime.Edit) -> None:
        sublime.get_clipboard_async(callback=self.convert)

    def convert(self, text: str) -> None:
        text = text.strip()
        if not text:
            window = self.view.window()
            if window:
                window.status_message("No text to paste!")
            return

        session = self.session_by_name()
        if not session:
            window = self.view.window()
            if window:
                window.status_message("No language server session!")
            return

        session.send_request(
            request=Request(
                method="taplo/convertToJson",
                params={"text": text},
                view=self.view,
            ),
            on_result=self.paste_result,
        )

    def paste_result(self, response: dict[str, str]) -> None:
        error = response.get("error")
        if error:
            sublime.error_message(f"Failed to convert to JSON:\n\n{error}")
            return

        text = response.get("text")
        if not text:
            sublime.error_message("Converted content is empty, but it shouldn't!")
            return

        self.view.run_command("insert", {"characters": text})


class TaploPasteAsTomlCommand(LspTextCommand):
    """
    This class implements the `taplo_paste_as_toml` command.

    The command inserts JSON clipboard content at caret location(s) as TOML.
    """

    session_name = TaploPlugin.name()

    def run(self, _: sublime.Edit) -> None:
        sublime.get_clipboard_async(callback=self.convert)

    def convert(self, text: str) -> None:
        text = text.strip()
        if not text:
            window = self.view.window()
            if window:
                window.status_message("No text to paste!")
            return

        session = self.session_by_name()
        if not session:
            window = self.view.window()
            if window:
                window.status_message("No language server session!")
            return

        session.send_request(
            request=Request(
                method="taplo/convertToToml",
                params={"text": text},
                view=self.view,
            ),
            on_result=self.paste_result,
        )

    def paste_result(self, response: dict[str, str]) -> None:
        error = response.get("error")
        if error:
            sublime.error_message(f"Failed to convert to TOML:\n\n{error}")
            return

        text = response.get("text")
        if not text:
            sublime.error_message("Converted content is empty, but it shouldn't!")
            return

        self.view.run_command("insert", {"characters": text})


def plugin_loaded():
    register_plugin(TaploPlugin)


def plugin_unloaded():
    TaploPlugin.cleanup()
    unregister_plugin(TaploPlugin)
