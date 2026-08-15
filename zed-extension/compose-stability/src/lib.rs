use zed_extension_api::{self as zed, Result};

struct ComposeStability;

impl zed::Extension for ComposeStability {
    fn new() -> Self {
        Self
    }

    fn language_server_command(
        &mut self,
        _language_server_id: &zed::LanguageServerId,
        worktree: &zed::Worktree,
    ) -> Result<zed::Command> {
        let python = worktree
            .which("python3")
            .ok_or_else(|| "python3 not found on PATH".to_string())?;
        let script = format!("{}/scripts/compose-stability-lsp.py", worktree.root_path());
        Ok(zed::Command {
            command: python,
            args: vec![script],
            env: Default::default(),
        })
    }
}

zed::register_extension!(ComposeStability);
