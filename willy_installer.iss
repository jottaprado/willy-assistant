; Script de Instalação Inno Setup para o Willy 🎙️
; Copiloto de Voz Ultraleve com Whisper Large v3 e IA da Groq
; Desenvolvido para Windows 10 e Windows 11

; A versão vem de versao.py (fonte única), passada pelo build_installer.py --instalador
; como /DMyAppVersion=... Não escreva o número aqui.
#ifndef MyAppVersion
  #error "Gere o instalador com: .venv\Scripts\python.exe build_installer.py --instalador"
#endif
#define MyAppPublisher "Jotta Prado"
#define MyAppURL "https://github.com/jottaprado/willy-assistant"
; Os cinco abaixo só mudam no teste de ponta a ponta do instalador, que instala um Willy de
; mentira (outro nome, AppId, executável e mutex) sem tocar na pasta, no valor do Run nem no
; atalho do Willy de verdade.
#ifndef MyAppName
  #define MyAppName "Willy"
#endif
#ifndef MyAppId
  #define MyAppId "{{E14A7923-40B1-4BF2-82E6-B91DF2F3B901}"
#endif
#ifndef MyAppExeName
  #define MyAppExeName "Willy.exe"
#endif
; O mesmo nome do SingleInstanceManager (core/single_instance.py): o Willy aberto o segura.
#ifndef MyAppMutex
  #define MyAppMutex "Local\WillyApp_SingleInstance_Mutex_98a7"
#endif
#ifndef MyAppSourceDir
  #define MyAppSourceDir "dist\Willy"
#endif

[Setup]
; Identificador único da aplicação (GUID gerado especificamente para o Willy)
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
; Executável com ícone oficial
SetupIconFile=assets\willy_icon.ico
UninstallDisplayIcon={app}\assets\willy_icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
OutputDir=dist_installer
OutputBaseFilename=Willy-Setup-v{#MyAppVersion}
; O Willy fica na bandeja quando a janela fecha: atualizar com ele aberto falhava no
; Willy.exe travado ou deixava a pasta pela metade. O [Code] o fecha antes; o AppMutex é a
; rede para quando não der (pede para fechar em vez de seguir), e o CloseApplications pega
; outro processo que esteja usando arquivos da pasta.
AppMutex={#MyAppMutex}
CloseApplications=force
; Quem abre de novo o Willy que o [Code] fechou é o [Run] do fim da instalação (o
; postinstall, ou o ReabrirNoSilencioso), ou o DeinitializeSetup se a pessoa desistir.
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; Só na primeira instalação. Numa atualização quem decide é o estado de antes (ver
; LigarInicioComOWindows): o Inno lembraria a tarefa marcada lá atrás e religaria o início que a
; pessoa desligou no Ajustes.
Name: "startupicon"; Description: "Iniciar o Willy automaticamente com o Windows (Recomendado)"; GroupDescription: "Inicialização do Sistema:"; Check: PrimeiraInstalacao

[InstallDelete]
; O runtime da versão anterior sai inteiro: copiar por cima deixava módulos e DLLs que a
; nova versão não tem mais. Os dados da pessoa ficam em %APPDATA%\Willy, fora daqui.
Type: filesandordirs; Name: "{app}\_internal"
; Até a 1.6.0 o início com o Windows era um atalho na pasta Inicializar. Agora é o valor
; "Willy" no Run, o mesmo que o Ajustes liga e desliga: com os dois, o Willy abria duas vezes.
Type: files; Name: "{userstartup}\{#MyAppName}.lnk"

[Files]
; Todos os arquivos da pasta compilada pelo PyInstaller
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\willy_icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\willy_icon.ico"; Tasks: desktopicon

[Registry]
; Início com o Windows no mesmo lugar e no mesmo formato que o AutoStartManager
; (core/autostart.py) usa: o interruptor do Ajustes passa a enxergar o que o instalador ligou.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Check: LigarInicioComOWindows; Flags: uninsdeletevalue
; Sem a tarefa marcada, o valor pode ter sido ligado pelo Ajustes: a desinstalação o tira do
; mesmo jeito, senão o Windows tentaria abrir um Willy.exe que não existe mais a cada logon.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "{#MyAppName}"; Flags: uninsdeletevalue dontcreatekey

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
; Silenciosa, a de cima não roda: o Willy que estava aberto ficaria fechado depois da atualização.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait; Check: ReabrirNoSilencioso

[Code]
const
  CHAVE_RUN = 'Software\Microsoft\Windows\CurrentVersion\Run';

var
  // Já havia um Willy instalado por este instalador: é uma atualização. A chave de
  // desinstalação e o Willy.exe na pasta que ela registra: a chave sozinha fica órfã quando a
  // pasta é apagada à mão ou a desinstalação é interrompida, e aí é instalação nova.
  EhAtualizacao: Boolean;
  // Antes da atualização o Willy iniciava com o Windows: o valor no Run (o interruptor do
  // Ajustes) ou o Willy.lnk da pasta Inicializar das versões até a 1.6.0, que o [InstallDelete]
  // apaga. Lido no InitializeSetup, antes de a instalação mexer em qualquer um dos dois.
  InicioLigadoAntes: Boolean;
  // O instalador fechou um Willy que estava aberto; ele volta no fim (ver [Run]) ou na desistência.
  WillyFechado: Boolean;
  // Os arquivos já foram trocados (ou removidos): desistir não volta mais atrás.
  Concluido: Boolean;

// InitializeSetup e InitializeUninstall rodam antes da checagem do AppMutex (medido): fechar
// o Willy aqui evita a mensagem que mandava a pessoa achar o ícone da bandeja e sair por lá.
function WillyAberto(): Boolean;
begin
  Result := CheckForMutexes('{#MyAppMutex}');
end;

// Tenta primeiro um taskkill gracioso (sem /F) e aguarda até 2 s. Como o X da janela do Willy
// só a esconde na bandeja quando recebe WM_CLOSE, recorre ao /F se o processo continuar aberto.
procedure EncerrarWilly();
var
  Codigo, Tentativas: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM {#MyAppExeName}', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
  Tentativas := 0;
  while WillyAberto() and (Tentativas < 20) do
  begin
    Sleep(100);
    Tentativas := Tentativas + 1;
  end;
  if WillyAberto() then
  begin
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#MyAppExeName}', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
    // O mutex some quando o processo termina de fato, um instante depois do taskkill.
    Tentativas := 0;
    while WillyAberto() and (Tentativas < 30) do
    begin
      Sleep(100);
      Tentativas := Tentativas + 1;
    end;
  end;
  WillyFechado := not WillyAberto();
  Log(Format('Willy encerrado pelo instalador (taskkill %d, fechou: %d)', [Codigo, Ord(WillyFechado)]));
end;

procedure ReabrirWilly();
var
  Codigo: Integer;
begin
  try
    Exec(ExpandConstant('{app}\{#MyAppExeName}'), '', '', SW_SHOWNORMAL, ewNoWait, Codigo);
  except
    // {app} ainda não definido (a desistência veio antes do assistente): não há o que abrir.
  end;
end;

// Interativo, avisa e deixa desistir; silencioso (/SILENT, /VERYSILENT), só fecha.
function PodeFecharWilly(Silencioso: Boolean; const Acao: String): Boolean;
begin
  Result := True;
  if not WillyAberto() then
    Exit;
  if not Silencioso then
    Result := MsgBox('O Willy está aberto e vai ser fechado para a ' + Acao + '.' + #13#10 +
      'Continuar?', mbConfirmation, MB_OKCANCEL) = IDOK;
  if Result then
    EncerrarWilly();
end;

function InitializeSetup(): Boolean;
var
  ChaveDesinstalacao, PastaAnterior, ValorRun: String;
begin
  ChaveDesinstalacao := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + ExpandConstant('{#MyAppId}') + '_is1';
  EhAtualizacao := False;
  if RegQueryStringValue(HKCU, ChaveDesinstalacao, 'InstallLocation', PastaAnterior) or
     RegQueryStringValue(HKLM, ChaveDesinstalacao, 'InstallLocation', PastaAnterior) then
    EhAtualizacao := FileExists(AddBackslash(PastaAnterior) + '{#MyAppExeName}');
  // Valor vazio conta como desligado, como no AutoStartManager.is_enabled.
  InicioLigadoAntes := (RegQueryStringValue(HKCU, CHAVE_RUN, '{#MyAppName}', ValorRun) and (Trim(ValorRun) <> '')) or
    FileExists(ExpandConstant('{userstartup}\{#MyAppName}.lnk'));
  Log(Format('Atualização: %d; início com o Windows antes: %d', [Ord(EhAtualizacao), Ord(InicioLigadoAntes)]));
  Result := PodeFecharWilly(WizardSilent(), 'atualização');
end;

function PrimeiraInstalacao(): Boolean;
begin
  Result := not EhAtualizacao;
end;

// Primeira instalação: a tarefa (marcada por padrão). Atualização: o estado de antes. Sem
// isto, o Inno religava o início desligado no Ajustes (lembra a tarefa da primeira vez), e uma
// instalação antiga sem a tarefa registrada perdia o início que vinha do Willy.lnk.
function LigarInicioComOWindows(): Boolean;
begin
  if EhAtualizacao then
    Result := InicioLigadoAntes
  else
    Result := WizardIsTaskSelected('startupicon');
end;

function InitializeUninstall(): Boolean;
begin
  Result := PodeFecharWilly(UninstallSilent(), 'desinstalação');
end;

function ReabrirNoSilencioso(): Boolean;
begin
  Result := WizardSilent() and WillyFechado;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    Concluido := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    Concluido := True;
end;

// Desistiu depois de o Willy ser fechado: ele volta a abrir, como estava.
procedure DeinitializeSetup();
begin
  if WillyFechado and not Concluido then
    ReabrirWilly();
end;

procedure DeinitializeUninstall();
begin
  if WillyFechado and not Concluido then
    ReabrirWilly();
end;
