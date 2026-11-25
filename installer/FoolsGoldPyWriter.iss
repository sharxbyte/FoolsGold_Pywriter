; Inno Setup script for the FoolsGold PyWriter Windows installer.
; Built by  python build.py --installer  (or CI), which passes:
;   /DAppVersion=1.2.3  /DAppVersion4=1.2.3.0  /DSourceDir=<the Nuitka dist folder>  /DOutputDir=<where to write setup.exe>
; Compile by hand with Inno Setup 6:
;   ISCC.exe /DAppVersion=1.0.1 /DSourceDir=..\dist\FoolsGoldPyWriter /DOutputDir=..\dist FoolsGoldPyWriter.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppVersion4
  #define AppVersion4 AppVersion + ".0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\FoolsGoldPyWriter"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#define AppName "FoolsGold PyWriter"
#define AppExe "FoolsGoldPyWriter.exe"
#define AppPublisher "sharxbyte"
#define AppURL "https://github.com/sharxbyte/FoolsGold_Pywriter"

[Setup]
; Never change AppId: Windows uses it to recognise upgrades and the uninstaller.
AppId={{614AEA9E-964E-498E-B3E7-802883937E6C}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
AppCopyright=Copyright (C) 2023-2026 sharxbyte. GPL-3.0-or-later.
VersionInfoVersion={#AppVersion4}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion4}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Setup
; Installs for the current user without an admin prompt; the user can choose
; "Install for all users" instead.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\TERMS-OF-USE.md
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
SetupIconFile=..\pywriter\resources\Icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir={#OutputDir}
OutputBaseFilename=FoolsGoldPyWriter-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The whole Nuitka folder build: the program, its DLLs, Qt plugins, data and license files.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Read me"; Filename: "{app}\README.md"
Name: "{group}\License and terms of use"; Filename: "{app}\TERMS-OF-USE.md"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Messages]
FinishedLabel=Setup has finished installing [name] on your computer.%n%nYour projects are stored in Documents\PyWriter Projects. Uninstalling PyWriter never deletes them, or the speech and voice models you download (in %APPDATA%\PyWriter).
