; Установщик «Сделки amoCRM» (Inno Setup 6).
; Собирает dist\SdelkiAmoCRM\ (результат PyInstaller) в один файл SdelkiAmoCRM-Setup.exe.
; Сборка: iscc /DAppVersion=1.0.2 installer.iss
;
; Ставится в профиль пользователя (%LOCALAPPDATA%\Programs) — права администратора не нужны.
; Данные (вход в amoCRM, созданные сделки, журнал) лежат отдельно в %LOCALAPPDATA%\amoCRMorders
; и при обновлении/удалении не трогаются.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B7E2C1A-4F3D-4E8B-9A51-0C2D7F3E9B11}
AppName=Сделки amoCRM
AppVersion={#AppVersion}
AppVerName=Сделки amoCRM {#AppVersion}
AppPublisher=YourDax
AppPublisherURL=https://github.com/YourDax/amoCRMorders
AppUpdatesURL=https://github.com/YourDax/amoCRMorders/releases
DefaultDirName={localappdata}\Programs\SdelkiAmoCRM
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=SdelkiAmoCRM-Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\SdelkiAmoCRM.exe
UninstallDisplayName=Сделки amoCRM
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Сделки amoCRM
VersionInfoDescription=Установщик «Сделки amoCRM»
VersionInfoCompany=YourDax

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; GroupDescription: "Ярлыки:"

[Files]
Source: "dist\SdelkiAmoCRM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; при обновлении убрать файлы старой версии
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{userprograms}\Сделки amoCRM"; Filename: "{app}\SdelkiAmoCRM.exe"
Name: "{userdesktop}\Сделки amoCRM"; Filename: "{app}\SdelkiAmoCRM.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SdelkiAmoCRM.exe"; Description: "Запустить «Сделки amoCRM»"; Flags: nowait postinstall skipifsilent

[Code]
// Старая копия программы могла остаться запущенной (её сервер, драйвер Playwright и браузер amoCRM).
// Её файлы заняты, и обновление не встаёт. Закрываем её вместе с дочерними процессами.
procedure CloseRunningApp();
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM SdelkiAmoCRM.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  if Code = 0 then
    Sleep(1500);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  CloseRunningApp();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  CloseRunningApp();
  Result := True;
end;
