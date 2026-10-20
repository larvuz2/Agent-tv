# Setting up Agent TV at home (no experience needed)

Nothing gets installed on the TV. You set this up on a **computer** (Mac or
Windows laptop/desktop) that is on the **same Wi-Fi** as the TV. That computer
talks to the TV; Claude runs on that computer.

```
 phone / laptop ──▶ Claude on your home computer ──Wi-Fi──▶ LG TV
```

You need: the computer, your Claude account (the same one you use on claude.ai),
the TV remote, and about 15 minutes.

---

## Step 1 · Prepare the TV (2 min, with the remote)

1. Turn the TV on.
2. Open **Settings** (gear button) › **All Settings** › **General** › **Devices** ›
   **External Devices** › **TV On With Mobile** and switch on **Turn on via Wi-Fi**.
   (On older TVs it's under **Connection** › **Mobile Connection Management**.)
3. In **General** › **Additional Settings**, switch on **Quick Start+**.
4. Optional but helpful: write down the TV's IP address from **Settings** ›
   **Network** › **Wi-Fi Connection** (or **Wired**) › **Advanced Settings**.
   It looks like `192.168.1.50`.

If a menu name doesn't match, use the TV's settings search; names change by year.

---

## Step 2 · Open the Terminal

The Terminal is an app where you paste commands. You'll paste a few lines and
press **Enter** after each.

* **Mac:** press `⌘ Command` + `Space`, type **Terminal**, press **Enter**.
* **Windows:** see [Windows](#windows) at the bottom.

---

## Step 3 · Install Claude Code (Mac)

Paste this into Terminal and press Enter:

```sh
curl -fsSL https://claude.ai/install.sh | bash
```

When it finishes, **close the Terminal window and open a new one** (so it finds
the `claude` command).

---

## Step 4 · Download this project and set it up (Mac)

Paste these four lines (you can paste them all at once):

```sh
git clone -b claude/keen-brahmagupta-37rgd5 https://github.com/larvuz2/Agent-tv.git ~/Agent-tv
cd ~/Agent-tv
sh scripts/setup.sh
claude
```

* If a window pops up saying **"git" requires command line developer tools**,
  click **Install**, wait for it to finish (a few minutes), then paste the lines again.
* The project lands in a folder called **Agent-tv** in your home folder.
* `sh scripts/setup.sh` installs everything the project needs (1–2 minutes).
* `claude` starts Claude. The first time:
  1. A browser opens to **log in** with your Claude account. Approve it.
  2. Claude asks whether you **trust this folder**: choose **Yes**.
  3. Claude asks whether to use the **lg-tv MCP server** from `.mcp.json`:
     choose to **allow/use** it.

---

## Step 5 · Connect Claude to the TV

Make sure the TV is on. In the Claude window, type:

> Find my LG TV and pair with it.

Claude searches the network and connects. **The TV shows a "connection request"
pop-up: press Accept on the remote.** The TV then shows *"Claude is connected"*.

Now try:

> What's on the TV right now?
> Play lo-fi hip hop on YouTube.
> Switch to HDMI 2 and set the volume to 15.
> Turn off the home screen ads.

---

## Step 6 (optional) · Control it from your phone

Claude has to keep running on the home computer. In Terminal:

```sh
cd ~/Agent-tv
claude remote-control
```

Leave that window open. Open the **Claude app** on your phone (or claude.ai):
the session from your computer shows up there, and you can type requests from
the couch.

Keep the computer awake while you want phone control. On a Mac you can run
`caffeinate -i claude remote-control` instead, which stops it sleeping.

---

## Next time

Open Terminal and paste:

```sh
cd ~/Agent-tv && claude
```

(or `claude remote-control` for phone control). No pairing needed again.

---

## Windows

1. Install **Git for Windows** from <https://git-scm.com/download/win> (accept the defaults).
2. Install **Python 3.12** from the Microsoft Store (search "Python 3.12"), or from python.org
   (tick **Add python.exe to PATH**).
3. Open **PowerShell** (Start menu › type *PowerShell*) and install Claude Code:

   ```powershell
   irm https://claude.ai/install.ps1 | iex
   ```

4. Close PowerShell, open it again, then:

   ```powershell
   git clone -b claude/keen-brahmagupta-37rgd5 https://github.com/larvuz2/Agent-tv.git $HOME\Agent-tv
   cd $HOME\Agent-tv
   claude
   ```

5. In Claude, type: **"Set this project up for Windows and connect to my LG TV."**
   Claude will create the Python environment, register the TV tools for this
   folder, and pair (press **Accept** on the TV).
   (For reference, the commands are in the README under *Windows*.)

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `command not found: claude` | Close the Terminal and open a new one. |
| "No LG TVs found" | TV on? Computer on the same Wi-Fi (not guest Wi-Fi, no VPN)? Tell Claude the TV's IP address. |
| No pop-up on the TV | Ask Claude to pair again and watch the screen; it disappears after a while. |
| Claude says the lg-tv tools aren't available | Type `/mcp` in Claude to see the server; or quit (`/exit`) and run `claude` again. |
| Phone can't see the session | Make sure `claude remote-control` is still running and the computer is awake. |
