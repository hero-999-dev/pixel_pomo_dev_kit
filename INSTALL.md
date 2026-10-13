## Install on a Mac

> This is a first Mac build. It was built and started on GitHub's Macs, with no
> window; nobody has yet opened it on a Mac with a screen. If a step does not go
> as written here, what happened instead is worth reporting exactly.

**One line, and no warning from macOS.** Open **Terminal** (press `Cmd` +
`Space`, type `Terminal`, press `Enter`), paste this and press `Enter`:

```sh
curl -fsSL https://github.com/hero-999-dev/pixel_pomo_dev_kit/releases/latest/download/install-mac.sh | sh
```

It picks the right build for your Mac (Apple Silicon or Intel), fetches it and
opens the setup. macOS shows no "Apple could not verify…" warning, because a
file fetched this way is not marked as a download from a browser.

**In the setup window**, the Dev Kit suggests where it should live:

```
/Applications/PixelPomoDevKit
```

Leave it, or choose another folder, and press **INSTALL**, then **OPEN THE DEV
KIT**. Do not choose Documents, Desktop or Downloads: those are the three
folders macOS asks permission for.

**From now on** open it from `/Applications/PixelPomoDevKit/PixelPomoDevKit.app`
— drag it to the Dock to keep it there.

Everything you add is kept in `/Applications/PixelPomoDevKit/Files/`, each file
under its own name. Click the version number, top left in the kit, to see the
folders and open them.

<details>
<summary><b>If you would rather download it yourself</b></summary>

1. Apple menu () → **About This Mac**. **Chip** Apple M1, M2, M3 … is
   `PixelPomoDevKit-macos-apple-silicon.zip`; **Processor** … Intel … is
   `PixelPomoDevKit-macos-intel.zip`.
2. Download that file from **Assets**, at the bottom of this page. Safari
   unzips it by itself: you get a folder called `PixelPomoDevKit-macos-…` in
   **Downloads**. If you still see the `.zip` there, double-click it once.
3. Do not double-click the app yet. The Dev Kit is not signed with a paid Apple
   developer account, so macOS refuses to open it straight from a browser's
   download. One line in Terminal removes that mark and opens it:

   ```sh
   cd ~/Downloads && xattr -dr com.apple.quarantine PixelPomoDevKit-macos-* && open PixelPomoDevKit-macos-*/PixelPomoDevKit.app
   ```

   Nothing is printed when it works. The setup window opens; carry on as above.
   The folder in Downloads can go in the Trash afterwards.

</details>

<details>
<summary><b>If you already double-clicked a download and macOS said no</b></summary>

Nothing is broken. Click **Done** on the warning (not *Move to Trash*), then
either run the line from step 3 above, or without Terminal:

1. Apple menu → **System Settings** → **Privacy & Security**.
2. Scroll down to *"PixelPomoDevKit" was blocked to protect your Mac*.
3. Click **Open Anyway**, and confirm with your password or Touch ID.

</details>

<details>
<summary><b>If Terminal says "No such file or directory"</b></summary>

That is the line for a download you made yourself, and the download is not in
Downloads, or is still a `.zip`. Double-click the `.zip` first. If you saved it
somewhere else, type `xattr -dr com.apple.quarantine ` (with the space at the
end), drag the `PixelPomoDevKit` app from Finder onto the Terminal window,
press `Enter`, and then double-click the app.

</details>

## Install on Windows

1. Download `PixelPomoDevKit-windows.zip` from **Assets** below and unzip it.
2. Double-click `PixelPomoDevKit.exe`. The first time, Windows says *"Windows
   protected your PC"*, because the program is not signed: click **More info**,
   then **Run anyway**.
3. The setup suggests `C:\Program Files\PixelPomoDevKit`. Press **INSTALL**.
   Windows asks once whether the program may be put there — say **Yes**. If
   the setup says it is waiting for Windows and you see no question, the
   question opened behind the window: click the shield flashing on the
   taskbar. (A folder of your own, like `D:\Tools`, is not asked about.)
4. Start it from the shortcut on the Desktop. The download is no longer needed.

## Already have it?

**UPDATE**, top right in the kit, lights up when a newer version is out — the
kit looks each time it opens. Click it: the kit downloads the new version,
closes, and opens again as it. Everything you added stays where it is.

## What it does

Add an Art Kit sprite export (`.png`) or a MagicaVoxel model (`.vox`) and see it
standing in Pixel Pomo's garden, drawn by the game's own engine. **GUIDE**, in
the kit's top bar, explains the rest; `READ-ME-FIRST` is in every download.
