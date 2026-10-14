# Running pk from anywhere

There are two different ways `pk` is ran:

- **As a command** from the `qcdx` package. The installer puts a `pk`
  executable on the systems `PATH`, allowing it to work from every shell: bash,
  zsh, PowerShell, cmd, MSYS2, etc. The **same command** is also installed as
  `qcdx`; the two are identical, and `qcdx` is the name `uvx qcdx` and
  `pipx run qcdx` look for when running QCDX without installing it.
- **As a script** inside every QCDX kitted project, at `scripts/pk.py`. Nothing
  needs to be installed besides Python, and it only works inside that project.

The installed command knows where it runs:

| Where you run it | What `pk` does |
| --- | --- |
| Outside any project | `pk new`, `pk list`, `pk tree`, `pk --version`, `pk cmake-dir` and `pk help` |
| Anywhere inside a project | runs that project's own `scripts/pk.py` (wherever its tree puts the scripts) with the same arguments |

Inside of QCDX kitted project, the pk version the project vendors is the
version used. Upgrading QCDX does not change your existing projects: `pk sync`
inside of that project does, when asked for.

Pick the section that matches how you want to use/install QCDX:

| How you got QCDX | Section |
| --- | --- |
| `pk` command works everywhere | [1. Install from PyPI](#1-install-from-pypi) |
| Working on QCDX, from a clone | [2. Install from a clone](#2-install-from-a-clone) |
| Python Zip Application (`pk.pyz`) | [3. Run the single-file pk.pyz](#3-run-the-single-file-pkpyz) |
| No install / just testing | [4. Use the project's own script](#4-use-the-projects-own-script) |

*Every section requires Python 3.9 or newer.*

## 1. Install from PyPI

This is the recommended way. Use one of the three installers below and then
follow [Make sure your shell finds pk](#make-sure-shell-finds-pk).

### pipx (recommended)

pipx installs `pk` into its isolated environment, never conflicting with
packages of your other Python projects.

*On Windows, run `py -m pipx` instead of `pipx` until the `ensurepath` command
has been executed and has taken effect.*

```bash
pipx install qcdx
pipx ensurepath # Ensure directories necessary for pipx operation are in your
                # PATH environment variable.
```

If **you don't have pipx** yet:

| Platform (common shell) | Command |
| --- | --- |
| Windows (PowerShell) | `py -m pip install --user pipx` |
| MSYS2 (UCRT64) | `pacman -S mingw-w64-ucrt-x86_64-python-pipx` |
| macOS (zsh) | `brew install pipx` |
| Debian / Ubuntu (bash) | `sudo apt install pipx` |
| Fedora (bash) | `sudo dnf install pipx` |

QCDX needs Conan, CMake and Ninja to be able to build anything. On a machine
that has none of them yet, the `tools` extra installs them alongside `pk` (you
still need compiler(s)):

```bash
pipx install "qcdx[tools]"
```

*Tools* already installed on the system are always used over the ones the extra
brings in.

**Update or remove** it later:

```bash
pipx upgrade qcdx
pipx uninstall qcdx
```

### uv

```bash
uv tool install qcdx
uv tool update-shell
```

Update via `uv tool upgrade qcdx`.

### pip

Only use plain pip when you can't use pipx or uv. A user install will share its
environment with every package installed the same way on the system.

```bash
python -m pip install --user qcdx
```

pip will not add its scripts directory to `PATH`. Find it with:

```bash
python -m site --user-base
```

The `pk` executable is in the `Scripts` folder (Windows) or the `bin` folder
(macOS and Linux) under the printed path. Add that folder to `PATH` as shown
in [Make sure shell finds pk](#make-sure-shell-finds-pk).

## 2. Install from a clone

For working on QCDX. The editable install runs the code in your clone; all
changes take effect instantly.

```bash
git clone https://github.com/cooldood155/QCDX.git
cd QCDX
pipx install -e .
```

If `pk` is already installed from PyPI, pipx keeps the existing one and does
not install the clone. Replace it with:

```bash
pipx install -e . --force
```

Moving or deleting the clone will then break `pk` until you install it again.

## 3. Run the single-file pk.pyz

Every [GitHub release](https://github.com/cooldood155/QCDX/releases) has
`pk.pyz`, which is all of QCDX in one file, needing nothing besides a Python
interpreter. It's the quickest way to create a project, just calling it like a
normal python script:

```bash
python pk.pyz new myproject
```

To run it as `pk` from anywhere on macOS and Linux, copy it into a folder on
(or added to) your `PATH`:

```bash
install -m 755 pk.pyz ~/.local/bin/pk
```

On Windows, Python does not run a `.pyz` file by its bare name from every
shell. Use [pipx](#pipx-recommended) there to get `pk` everywhere.

## 4. Use the project's own script

Every QCDX kitted project has `scripts/pk.py`. Without a project yet, one must
be create (shown how without installing QCDX below) in any of these ways:

```bash
gh repo create myproject --template cooldood155/QCDX-template --public --clone

# or

uvx qcdx new myproject       # uv: runs QCDX without an install

# or

pipx run qcdx new myproject  # pipx: the same as uvx
```

Without the GitHub CLI you can just press **Use this template** on the
[QCDX-template](https://github.com/cooldood155/QCDX-template) page and clone
the new repository.

Then run `scripts/pk.py` from the project root:

```bash
./scripts/pk.py build # bash, zsh, MSYS2
```

```powershell
python scripts\pk.py build  # PowerShell, cmd
```

To type `pk` instead of invoking the projects python script directly, install
the shell function. It will run the nearest `scripts/pk.py` above the CWD,
allowing `pk` to work anywhere inside any QCDX project, with tab completion.
Outside of a project it finds nothing to run and reports an error.

### bash, zsh and MSYS2

Run this from inside any QCDX project:

```bash
./scripts/pk.py shell-init > "$HOME/.pk.bash"
printf '\n# QCDX pk command\n[ -f "$HOME/.pk.bash" ] && . "$HOME/.pk.bash"\n' >> "$HOME/.bashrc"
source "$HOME/.bashrc"
```

### PowerShell

Run this from inside any QCDX project:

```powershell
python scripts\pk.py shell-init powershell | Out-File -Encoding ascii "$HOME\.pk.ps1"
if (-not (Test-Path $PROFILE)) { New-Item -ItemType File -Path $PROFILE -Force | Out-Null }
Add-Content $PROFILE '. "$HOME\.pk.ps1"'
. $PROFILE
```

If PowerShell refuses to load your profile, you may need to allow local scripts
for your user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

The shell function and the installed command are both `pk`. Use one or the
other: a shell runs a function before it searches `PATH`, and the
function hides the installed command. The installed command does everything
the function does while also working outside of a project.

## Make sure shell finds pk

`pipx ensurepath` and/or `uv tool update-shell` add the install folder to your
user `PATH`. Open a **new** terminal aftre this is done; an already opened
terminal will keep its old `PATH`.

### Windows PowerShell and cmd

Nothing else to do after a new terminal. To see the folder pipx uses:

```powershell
pipx environment --value PIPX_BIN_DIR
```

### MSYS2

MSYS2 does not read the Windows `PATH` by default, and it does not see the
directory `ensurepath` added. Add it to `~/.bashrc` if needed:

```bash
if [[ ":$PATH:" != *":$(cygpath -u "$USERPROFILE")/.local/bin:"* ]]; then
    export PATH="$(cygpath -u "$USERPROFILE")/.local/bin:$PATH"
fi
```

Then reload it:

```bash
source ~/.bashrc
```

This is the pipx default directory. If `pipx environment --value PIPX_BIN_DIR`
prints a different path use that one instead.

### macOS and Linux

Nothing else to do after a new terminal. pipx and uv install into
`~/.local/bin`, which `ensurepath` and `update-shell` already add to the
shell's startup file.

## Check it works

### Installed command (sections 1 to 3)

Run the check from a folder outside any project. `pk --version` should print
`QCDX` and it's version:

```bash
cd ~
type -a pk  # (bash, zsh, MSYS2) list every pk in order of 'execution'
pk --version
```

```powershell
Set-Location $HOME
Get-Command pk -All | Format-Table CommandType, Source
pk --version
```

```bat
cd /d %USERPROFILE%
where pk
pk --version
```

### Project script (section 4)

The project's `scripts/pk.py` has no `--version` option or `new` command. Check
it via `status` instead:

```bash
pk status               # anywhere within project
./scripts/pk.py status  # from the project root
/path/to/project/scripts/pk.py status  # from anywhere
```

```powershell
pk status                   # anywhere within project
python scripts\pk.py status # from the project root
python C:\path\to\project\scripts\pk.py status  # from anywhere
```

`scripts/pk.py` always works on the project it belongs to, not matter where it
is executed from. The shell function is **different**: it searches upward from
the current directory for `scripts/pk.py` and only works within a project.

`status` prints the project name, its path and prefix, and its build trees.
With the shell function, `type -a pk` shows `pk is a function` (PowerShell:
`Get-Command pk` shows `Function`).

## Troubleshooting

**`pk: command not found` right after installing.** The terminal was open
before the install. Close it and open a new one. In MSYS2, follow the
[MSYS2](#msys2) steps above if it still fails.

**`type -a pk` says `pk is a function`, after installing the command.** An old
shell function hides the installed command. Remove the line that loads
`~/.pk.bash` from `~/.bashrc` (or the `.pk.ps1` line from your PowerShell
`$PROFILE`), then open a new terminal.

**`pk` works in one shell but not another.** Each Python installs into its own
folders. `pk` installed with MSYS2's Python is not visible to PowerShell, and
the reverse. Install it with the Python of the shell you use most, and add its
folder to the other shells `PATH`.

**`pk` says a command needs a project.** You attempted to run a project command
outside of a project. `cd` into one, or create one via `pk new NAME`.

**`pk` broke after moving a clone.** An editable install points at the
clone's folder. Run `pipx install -e . --force` from its new location.
