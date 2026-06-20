; SermonNotes.iss — Inno Setup script for the Sermon Notes Windows installer.
;
; Produces SermonNotes-Setup-<VERSION>.exe. The recipient double-clicks it,
; clicks Next a few times, and gets:
;   * The app installed to %LOCALAPPDATA%\Programs\SermonNotes\
;     (no admin rights needed)
;   * The LLM model deployed to %LOCALAPPDATA%\SermonNotes\models\
;   * Start Menu shortcut + (optional) Desktop shortcut
;   * Entry in "Apps & features" so they can uninstall the normal way
;
; Build:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" SermonNotes.iss
;
; Prerequisites:
;   * dist\SermonNotes\          (PyInstaller bundle — from make_release.bat)
;   * models\<MODEL_FILENAME>    (~2.4 GB LLM GGUF)

#define AppName "Sermon Notes"
#define AppVersion "1.0.0"
#define AppPublisher "Ian Jordan"
#define AppExeName "SermonNotes.exe"
#define ModelFilename "Phi-3.5-mini-instruct-Q4_K_M.gguf"

; AppId is the upgrade key — NEVER change this once a version has shipped.
; A consistent AppId lets a new installer detect and upgrade older installs
; in place rather than installing side-by-side.
#define AppId "{{B7A6E0F2-3C8E-4D9A-B14F-3D2C8E6F7A91}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/ianbarjordan/open-sermon-notes
AppSupportURL=https://github.com/ianbarjordan/open-sermon-notes/issues

; Per-user install — no admin / UAC prompt, lives under %LOCALAPPDATA%.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

DefaultDirName={localappdata}\Programs\SermonNotes
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; Compression matters here — the bundle is ~886 MB + a 2.4 GB model.
; lzma2/max trades CPU during the build for ~30% smaller installer.
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes

OutputBaseFilename=SermonNotes-Setup-{#AppVersion}
OutputDir=dist

; Visual polish — the wizard pages get a side bar / header background.
; Pulled from Inno Setup's bundled samples; can be replaced with custom art.
WizardStyle=modern

; Don't show the "Select Destination" page by default — the install path is
; almost always fine, and one fewer screen for the pastor.
DisableDirPage=auto
DisableReadyPage=no
DisableFinishedPage=no

; Uninstall icon in Apps & features
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}

; Architecture lock — x64 only.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; SetupIconFile= ; add a .ico once a brand asset exists

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; \
    Description: "Create a &Desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"

[Files]
; --- Application bundle (PyInstaller --onedir output) ----------------------
; Everything under dist\SermonNotes\ gets placed under {app}\ preserving
; the _internal\ subfolder layout PyInstaller expects.
Source: "dist\SermonNotes\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; --- LLM model file --------------------------------------------------------
; Lives outside the install dir so:
;   (a) reinstalling/upgrading the app doesn't have to re-copy 2.4 GB
;   (b) uninstalling the app doesn't blow away the user's downloaded model
;
; `onlyifdoesntexist` skips the copy entirely if the file is already there
; from a prior install — first-time installs do the full 2.4 GB extract,
; subsequent runs skip straight past it.
Source: "models\{#ModelFilename}"; \
    DestDir: "{localappdata}\SermonNotes\models"; \
    DestName: "{#ModelFilename}"; \
    Flags: onlyifdoesntexist external skipifsourcedoesntexist; \
    Check: ModelFileBundled

; --- README seen by the recipient at install time (for the README button) -
; (Optional — uncomment + ship a release-notes file if/when one exists.)
; Source: "INSTALL.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
; Start Menu — always created.
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    WorkingDir: "{app}"; \
    Comment: "Search your sermon notes offline"

; Desktop — optional via the Tasks page.
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    WorkingDir: "{app}"; \
    Comment: "Search your sermon notes offline"; \
    Tasks: desktopicon

[Run]
; Offer to launch right after install. The pastor can uncheck if they want.
Filename: "{app}\{#AppExeName}"; \
    Description: "Launch {#AppName} now"; \
    Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
; The app's working logs land in %LOCALAPPDATA%\SermonNotes\logs\ — leave
; those alone on uninstall (user may want them for debugging). Same for
; their search index and quarantine. The model is also preserved (lives
; under %LOCALAPPDATA%\SermonNotes\models\ which we never touch here).
;
; This section is intentionally empty: only files written under {app} get
; auto-removed, which is exactly what we want.

[Code]
// Skip the model-file Source line if models\<filename> doesn't exist on
// the build machine. Lets ISCC compile a "small" installer (no model
// bundled) for testing, while a normal release-build includes the model.
function ModelFileBundled(): Boolean;
var
  ModelPath: String;
begin
  ModelPath := ExpandConstant('{src}\models\{#ModelFilename}');
  Result := FileExists(ModelPath);
end;
