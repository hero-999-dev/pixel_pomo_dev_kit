## Install on a Mac

> This is the first Mac build. It was built and started on GitHub's Macs, with
> no window; nobody has yet opened it on a Mac with a screen. If a step does not
> go as written here, what happened instead is worth reporting exactly.

**1. Find out which Mac you have.** Apple menu () → **About This Mac**.

| It says | Download |
|---|---|
| **Chip** Apple M1, M2, M3 … | `PixelPomoDevKit-macos-apple-silicon.zip` |
| **Processor** … Intel … | `PixelPomoDevKit-macos-intel.zip` |

**2. Download that file** from **Assets**, at the bottom of this page. Safari
unzips it by itself: you get a folder called `PixelPomoDevKit-macos-…` in
**Downloads**. If you still see the `.zip` there, double-click it once.

**3. Do not double-click the app yet.** The Dev Kit is not signed with a paid
Apple developer account, so macOS refuses to open it straight from a download
("Apple could not verify…"). One line removes that mark and opens it. Open
**Terminal** (press `Cmd` + `Space`, type `Terminal`, press `Enter`), paste this
and press `Enter`:

```sh
cd ~/Downloads && xattr -dr com.apple.quarantine PixelPomoDevKit-macos-* && open PixelPomoDevKit-macos-*/PixelPomoDevKit.app
```

Nothing is printed when it works. The setup window opens.

**4. In the setup window**, the Dev Kit suggests where it should live:

```
/Applications/PixelPomoDevKit
```

Leave it, or choose another folder, and press **INSTALL**, then **OPEN THE DEV
KIT**. Do not choose Documents, Desktop or Downloads: those are the three
folders macOS asks permission for.

**5. From now on** open it from `/Applications/PixelPomoDevKit/PixelPomoDevKit.app`
— drag it to the Dock to keep it there. The folder in Downloads can go in the
Trash.

Everything you add is kept in `/Applications/PixelPomoDevKit/Files/`, each file
under its own name. Click the version number, top left in the kit, to see the
folders and open them.

<details>
<summary><b>If you already double-clicked it and macOS said no</b></summary>

Nothing is broken. Click **Done** on the warning (not *Move to Trash*), then
either run the line from step 3, or without Terminal:

1. Apple menu → **System Settings** → **Privacy & Security**.
2. Scroll down to *"PixelPomoDevKit" was blocked to protect your Mac*.
3. Click **Open Anyway**, and confirm with your password or Touch ID.

</details>

<details>
<summary><b>If Terminal says "No such file or directory"</b></summary>

The download is not in Downloads, or is still a `.zip`. Double-click the `.zip`
first. If you saved it somewhere else, type `xattr -dr com.apple.quarantine `
(with the space at the end), drag the `PixelPomoDevKit` app from Finder onto
the Terminal window, press `Enter`, and then double-click the app.

</details>

<details>
<summary><b>The one-line install</b> (only once this repository is public)</summary>

```sh
curl -fsSL https://github.com/hero-999-dev/pixel_pomo_dev_kit/releases/latest/download/install-mac.sh | sh
```

It picks the right build for your Mac, fetches it and opens the setup, with no
download to unzip and no warning to get past. While the repository is private
the line cannot reach the files, and says the download failed.

</details>

## Install on Windows

1. Download `PixelPomoDevKit-windows.zip` from **Assets** below and unzip it.
2. Double-click `PixelPomoDevKit.exe`. The first time, Windows says *"Windows
   protected your PC"*, because the program is not signed: click **More info**,
   then **Run anyway**.
3. The setup suggests `C:\Program Files\PixelPomoDevKit`. Press **INSTALL**.
   Windows asks once whether the program may be put there — say **Yes**. (A
   folder of your own, like `D:\Tools`, is not asked about.)
4. Start it from the shortcut on the Desktop. The download is no longer needed.

## What it does

Add an Art Kit sprite export (`.png`) or a MagicaVoxel model (`.vox`) and see it
standing in Pixel Pomo's garden, drawn by the game's own engine. **GUIDE**, in
the kit's top bar, explains the rest; `READ-ME-FIRST` is in every download.

**UPDATE**, top right, will fetch later versions by itself once this repository
is public. Until then, a newer download started the same way updates the
installed kit and keeps everything you added.
