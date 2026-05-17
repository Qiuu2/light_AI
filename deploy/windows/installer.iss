#define MyAppName "AI Speaker"
#ifndef AppVersion
#define AppVersion "1.0.0"
#endif
#ifndef SourceDir
#define SourceDir "."
#endif

[Setup]
AppId={{8A27E4D2-8F1B-4C1E-B4D9-A150EA501800}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher=AI Speaker
DefaultDirName={autopf}\AI Speaker
DefaultGroupName=AI Speaker
DisableProgramGroupPage=yes
OutputDir={#SourceDir}\installer
OutputBaseFilename=AI-Speaker-Setup-x64
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=AI Speaker
; setup.exe 自身的图标（同事下载下来看到的那个 .exe 文件图标）
SetupIconFile=assets\ai-speaker.ico
; 控制面板 "卸载或更改程序" 列表里 AI Speaker 那条的图标
UninstallDisplayIcon={app}\app.ico

[Languages]
; 安装向导自身的语言。Inno Setup 6.7+ 默认只装英文 isl 文件。
; 想加中文：从 https://github.com/jrsoftware/issrc/blob/main/Files/Languages/Unofficial/ChineseSimplified.isl
; 下载放到 "C:\Program Files (x86)\Inno Setup 6\Languages\" 后取消下行注释。
Name: "english"; MessagesFile: "compiler:Default.isl"
; Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\data\*"; DestDir: "{app}\data"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\web-dist\*"; DestDir: "{app}\web-dist"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\models\*"; DestDir: "{app}\models"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\runtime-data\*"; DestDir: "{commonappdata}\AI Speaker\data"; Flags: ignoreversion recursesubdirs createallsubdirs onlyifdoesntexist
Source: "{#SourceDir}\service\*"; DestDir: "{app}\service"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\manifest.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\checksums.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\ACCEPTANCE_CHECKLIST.md"; DestDir: "{app}"; Flags: ignoreversion
; 应用图标（被下面 [Icons] 段的 IconFilename 引用）
Source: "assets\ai-speaker.ico"; DestDir: "{app}"; DestName: "app.ico"; Flags: ignoreversion

[Dirs]
Name: "{commonappdata}\AI Speaker"
Name: "{commonappdata}\AI Speaker\data"
Name: "{commonappdata}\AI Speaker\logs"

[Icons]
; 开始菜单（统一加 IconFilename 用我们的 logo）
Name: "{group}\AI Speaker"; Filename: "http://127.0.0.1:5018/"; IconFilename: "{app}\app.ico"; Comment: "打开 AI Speaker 控制台"
Name: "{group}\查看日志"; Filename: "{commonappdata}\AI Speaker\logs"; Comment: "打开运行日志目录"
Name: "{group}\重启 AI Speaker 服务"; Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -NoProfile -Command ""Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-Command','Restart-Service -Name ai-speaker'"""; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"; Comment: "以管理员身份重启服务"
Name: "{group}\卸载 AI Speaker"; Filename: "{uninstallexe}"; Comment: "卸载 AI Speaker"

; 桌面快捷方式：同时写公共桌面 + 当前用户桌面，避免合并失效问题。两者都用我们的 logo
Name: "{commondesktop}\AI Speaker"; Filename: "http://127.0.0.1:5018/"; IconFilename: "{app}\app.ico"; Comment: "打开 AI Speaker 控制台"; Tasks: desktopicon
Name: "{userdesktop}\AI Speaker"; Filename: "http://127.0.0.1:5018/"; IconFilename: "{app}\app.ico"; Comment: "打开 AI Speaker 控制台"; Tasks: desktopicon

[Run]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -NoProfile -File ""{app}\service\install-service.ps1"" -InstallRoot ""{app}"""; Flags: runhidden waituntilterminated
Filename: "http://127.0.0.1:5018/"; Description: "Open AI Speaker"; Flags: postinstall shellexec skipifsilent unchecked

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -NoProfile -File ""{app}\service\uninstall-service.ps1"" -InstallRoot ""{app}"""; Flags: runhidden waituntilterminated; RunOnceId: "UninstallAISpeakerService"

[Code]
procedure StopAiSpeakerService();
var
  ResultCode: Integer;
begin
  // 升级时如果老服务还在跑，文件会被锁，安装会报 MoveFile failed code 5。
  // 在 [Files] 复制之前先停服务，并等几秒让 OS 释放文件句柄。
  Exec(ExpandConstant('{cmd}'), '/C sc stop ai-speaker', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  Sleep(3000);
  Exec(ExpandConstant('{cmd}'),
       '/C taskkill /F /IM ai-speaker-service.exe',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1500);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    // 在 [Files] 段复制文件之前停掉老服务（升级场景）
    StopAiSpeakerService();
  end;
  if CurStep = ssPostInstall then
  begin
    Log('AI Speaker installed. Runtime data is preserved under common app data.');
  end;
end;
