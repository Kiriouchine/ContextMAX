# Changelog

## 0.4.1 (2026-10-18)

- Measured with Claude Code agents on nine questions about two projects (one of 20,000 files), every answer
  checked against the source files: with the skill, none of 19 answers had a key fact wrong; without it, 2
  of 9 had one wrong. With this release, the agents with the skill took 29% less time and 18% fewer tokens
  than those without it on the first seven questions (1,892 s against 2,677 s), and 31% and 38% less time
  on two new questions. One run per question and arm: a single run can take much longer when the agent
  chooses to dig deeper.
- Ask: the model on this PC reads the code again. In 0.4.0 the ways in were one list (document values
  first, then the other documents with the same value name, then the code, the functions and the
  passages) cut to six places, so a value name in many spreadsheets filled every place and the code was
  never read ("What value does the laser control have for its limit?" read six budget sheets and said
  "not found"). Now every kind of way in (values, named numbers in the code, sections by their heading,
  functions, passages, pictures) is scored on one scale, a rare word of the question counting more, and
  the kinds take turns; a kind that holds less than half of what the best way in holds is not read.
- Ask: a value name is one way in, with one document read for each of its values; named numbers that
  differ only in their digits (`LASER_CONTROL_LIMIT_0` … `_46`) are one family, read once.
- Ask: where the model finds a way in that answers, ContextMAX looks up the rest in the files itself:
  every document that states that value, or every file that sets that named number with its value and
  the functions of its module that use it, each line checked in its file. The answer cites these
  look-ups, and the Ask page shows them with a link to each line.
- Ask: when the first six passages say nothing about the question, six more are read before "not found".
  A passage that answers any part of the question counts. A pointer that holds a code name
  ("line 4: #define LASER_CONTROL_LIMIT_0 528") is followed to that name.
- A way in for an AI in one call: `contextmax brief <project> "<question>"`. Two paired tests (Claude Code
  agents with the skill and without, on the same question) showed the index saved neither time nor tokens:
  an agent's time is its turns (about 9 s each), and the lookups returned long lists that took as many turns
  to digest as a search of its own. The brief gives, in one call (about 4 s on 10,000 documents and 62,500
  functions, under a second on a small project), the places to read (named values,
  named numbers in the code, sections, passages, functions, each with the line it points at), every file
  that sets each named number with its value and every use, and every document that states each value and
  whether they agree. It is the procedure that guides the model on this PC, without the model.
- The brief starts with what the question names exactly: a function with its callers (the line of each call),
  how far a change reaches and every document line that names it; a named number with its value and every
  use. In a paired test an assistant needed several lookups for "who calls laser_control_limit10_0?"; the
  brief now answers it in one call.
- When a question names a part of the code (a module of two words or more, such as laser_control), the brief
  keeps to it and adds a summary: every named number of the part (the definition in effect, the uses) and
  every value its documents state, marked where the documents differ. The question's own words (function,
  call, code, change, value) are not searched for: in a corpus that seldom uses them they outweighed the name
  the question was about.
- In a question about one part ("the encoder drive's nominal voltage"), the part's own words say where, not
  what: every name in the part holds them, so they count half, and a way in that holds nothing else of the
  question is not shown. In a second paired round, half the places of that brief were encoder_drive
  functions and a max current, none of them a voltage. The part's values are matched by whole words: the
  encoder drive, not the encoder driver.
- A code name that holds the initials of three or four words of the question in a row is a way in for them:
  `ekf_attitude_step` for "the extended Kalman filter", said as "(EKF: extended kalman filter)". That brief
  gave no code at all before.
- `params --compare` counts documents, then places: "61.8 V in 14 documents (27 places)", not "in 27".
- `find doc` gives every line of a document that says the words (up to 8), not only the best one.
- Fixed: a requirement that names its value in one word ("The pump control shall keep the timeout at
  435.7 s") gave no name, so `params --compare` called the pump control timeout a match while one document's
  requirement differs from its own list. The word now takes the fuller name its document gives ("Pump control
  timeout"); where the document gives none, the value stays without a name, as before.
- Fixed: "J1 = 0.0031 kg m2" (a PDF writes m² as m2) was read as kilograms; kg m2, kg m² and kg·m² are
  now one unit, kg·m².
- MATLAB named numbers with a name of two letters (I1, dt, Kp) are recorded, as in the other languages; a
  one-letter name still needs a comment that says what it is. `find symbol I1` found nothing in a project
  that sets it in fifty files.
- Fixed: a code name that starts a sentence ("Encoder_drive_handle10_5() …") was not linked to the code.
- Fixed: "the nominal voltage" and "the typical delay" gave no name ("nominal" and "typical" were treated as
  filler), so a requirement stating another value than the document's own list was not compared with it.
- Fixed: named numbers with a name of one or two letters (r1) recorded no uses, so they read as unused.
- Named numbers in the code record every use (file, line, the function it is in) in values.jsonl; a name
  defined in several places is used where its definition is in effect (the same file, else a header the file
  includes), and a value in a header records how many files include it. `find symbol|callers|impact` covers
  named numbers: where each is set, every use, and what a change reaches.
- `find doc` searches the documents' text too, each hit at the line that says most. The text and the
  headings are in a search store written by the build (documents/search.sqlite, counted in the outputs
  hash), so a lookup reads only what the words point to: the Ask page loads a 10,000-document project in
  about 2 s instead of 23. The store adds about 20 s to a build of that project (178 s in all, the same
  index byte for byte with one worker or eleven) and 92 MB to its working folder.
- `find` and `params` print plain text, every place cited and long lists cut with a count (`--json` for
  everything). `params --name` with no hit lists the names that share its words.
- The skill is two thirds of its size (9 KB instead of 14) and starts with the brief, in Bash, with the Python and the working
  folder written in (PowerShell adds a byte-order mark to piped output, which broke 4 of 9 lookups in a
  test); the description of every index file moved to references/index-files.md beside it.
- Fixed: every quoted `#include "x.h"` of C and C++ was stored as blanks (strings were blanked before the
  includes were read), so no file was known to include a project header.
- Fixed: a requirement sentence ("The laser control shall keep the max current at 15.0 A") named its value
  "max current", so it was compared with every part's max current and never with its own document's "Laser
  control max current: 12.5 A". A value named by its sentence now takes the fuller name its own document gives
  it, when exactly one name there ends with it.
- Fixed: a numbered name ("control limit 10") met a code name through one more word (LASER_CONTROL_LIMIT_10)
  in any document; it now meets it only where the document's name, sentence or section says that part too.
- `text-index.jsonl` calls the hash of a document's extracted text `text_sha256` (it was `sha256`, which read
  like the file's own hash: an assistant concluded from it that two different PDFs were the same file). An
  older index is renamed in place by the next build.
- Another tool's report about the project (a folder with Graphify's GRAPH_REPORT.md and graph.json) is not
  catalogued as a project document.
- Ask your AI: Claude Code is found where its installer puts it (`%USERPROFILE%\.local\bin\claude.exe`,
  a folder the installer does not add to the PATH), and Claude Code and Codex where npm puts them
  (`%APPDATA%\npm`). Before, the Claude Code button was missing and the card said "the claude command is
  not installed".

## 0.4.0 (2026-10-17)

A new ContextMAX, rebuilt around four layers that each answer one question: the catalogue (where is
each file), the document map (what was intended), the code map (what the code does) and the value
database (where a value comes from). The design from 0.1 to 0.3 is kept in git history (tag v0.3.1).

- Choose any number of folders per project, each holding code, documents or both; a window with the
  Windows folder picker, a readiness check and build buttons (`ContextMAX.cmd`).
- Code maps for C (macros that stand for functions, calls through pointers counted, names defined twice
  recorded), Python (resolution through imports and `self`), MATLAB (indexing told apart from calls)
  and VHDL (entity hierarchy, design top, orphans).
- C++ (`.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh`, `.hxx` and more, and every `.h` whose own text is C++) read
  by tree-sitter's C++ parser, pinned so every PC builds the same map: each function and method with its
  namespaces and class (`motor::Controller::clamp`), its kind (function, method, constructor, destructor,
  operator) and exact lines. Calls are followed through the caller's class and its base classes, the
  namespaces and `using namespace`, qualified names, and the declared type of the object (parameters,
  local variables, fields, `this`, pointers, references, smart pointers, type aliases, `auto` from
  `new`, `make_unique` and constructors); constructors count as calls (`Motor m(2)`, `new Motor`, base
  classes and fields a constructor initialises). Overloads are told apart by their number of arguments;
  a virtual method records the methods that override it. C++ calls C functions and C calls C++
  functions with C linkage. What the text cannot settle is counted, never guessed: a method called on an
  object of unknown type (with the name of the method and how many could be meant), a call through a
  variable, a field or a pointer. A file the parser cannot fully read is named in `overview.json`.
  Documents can name C++ code with its scope (`Controller::clamp`), and C++ constants (`#define`,
  `constexpr`, `const` in capitals) are names documents can link through. On 7,000 generated C++
  files the code map takes about 14 s and is the same, byte for byte, on every build.
- Large projects build much faster, with every result unchanged: placing a document on a part of the
  code reads its text once instead of once per module, and finding cited titles looks each title up by
  its first word and length. On a made-up project of 10,060 code files and 10,000 documents the build
  went from 21 to under 5 minutes (linking documents to code 570 s to 28 s, citations 372 s to 10 s),
  and every file of the index stayed byte for byte the same.
- The Complete Atlas: a page with everything in one drawing. Every module of every code base on a wheel,
  sized by its functions, with the calls between modules; every document in its lifecycle stage, next to
  the code it names most; and every link: documents to code, and documents to documents (cited, quoted,
  shared values, values that differ, same part of the code). Modules, documents and every line can be
  clicked; a double-click opens a module's functions with the modules it calls and is called from and
  the documents that name each function. Positions come from the data alone, so the same index draws the
  same picture. On 200 modules, 9,620 documents and 164,884 links it opens in about a second.
- The build can be watched live in the ContextMAX window (off unless switched on; the text log stays).
  The build reports what it has found as it goes, and the window draws it into the Complete Atlas:
  documents as they are read, the code as it is mapped, each document moving to its stage and then
  beside the code it names, the links as they are found, the validation gate at work, and at the end
  exactly the drawing of the Complete Atlas page. On 10,060 code files and 10,000 documents the
  build took 288.5 s with it and 288.7 s without, and the index is the same either way.
- Adding, removing or changing a folder in the window builds again at once (documents read, everything
  relinked), so a link across folders is never missed; a change during a build is built right after it.
  `contextmax folders` says to build again.
- Values stated in several documents are linked completely. Two documents that state values of the same
  names are linked however many such links a document already has (before: its eight strongest); for a name
  stated by more than twelve documents, each of them links to the first document that states the same
  value (before: no link at all); and when most documents agree on a value, each document that states
  another gets a red link to the first document stating the value most give, with both values and their
  cells (with no majority, as for a unit cost every bill of materials states differently, none is marked
  as the odd one out). Every name stated with more than one value is listed in
  `documents\value-conflicts.jsonl`, the gate recomputes the list and the red
  links from the value list, and the Home page counts them. Cited titles are no longer limited to forty
  per document. On the made-up project of 10,000 documents, links between documents went from 164,884
  to 225,370 (shared values 39,622 to 61,964, and 37,052 same-value and 1,092 red links), 14,257 names
  are stated with more than one value, and the build takes a few seconds longer.
- Fixed: the window ended a build's log with "doneCount." instead of "Done.".
- The window opens on a start screen: every project as a card (its folders, when it was built, its
  confidence, how many documents and functions) with a large **Open** button, the last one opened first,
  and **Start a new project** beside them. **Show the build live** is on the start screen and above the
  folder list, so it can be ticked before adding a folder starts a build; switched on during a build, the
  drawing starts from the build's first event (the build now always reports them; the window asks for
  them only while it draws). A built project shows its Complete Atlas at the bottom of the window; a live
  build draws into the same place.
- A project's screen starts with its name, what the last build made and a large **Open the project**
  button. **This PC** is as tall as the folders and the build beside it and scrolls inside. **Connect your
  AI** is a step of its own: what the skill does for Claude Code, for Copilot in VS Code, for Codex, and
  that a model on this PC needs none; whether it is installed for each, and whether it describes the
  last build. After a build in the window, a skill that is installed is brought up to date there.
- The build's log says what it is doing at every moment: the steps it will take, a header for each
  (`=== Step 3 of 6 · Code map (1:49)`) with the time it took, a line at least every two seconds in
  every long loop (`reading documents: 1,079 of 10,002 (10%) · DOC-15326 … · about 2 min left`), what
  changed since the last catalogue, and a summary at the end (files, documents, code, links, values,
  gate, pages, confidence). The window shows the steps, the line of the moment and a running clock above
  the log. On 10,000 documents and 10,060 code files the longest silence in the log went from 59 s to
  9 s, and the index is the same, byte for byte.
- The CMD window that runs ContextMAX shows what the window does, with the time: every line of a build,
  folders added and removed, the skill installed, assistants started, files opened, questions asked.
- Every build's log is saved in the working folder, `logs\build-<date>_<time>.txt` (the newest 30 are
  kept), with the time it started and ended and how; the window links to it. When the validation gate
  stops a build, the window says what it found.
- Fixed: two documents whose names differ only in capitals (`ReadMe.txt`, `readme.txt`) were given keys
  that Windows takes for one file name, so one document's text replaced the other's and the validation
  gate stopped the build at the end. Such names now get a key of their own each, as names that are the
  same do.
- **Add a folder…** is the largest button on a project's screen.
- The maps keep their view: switching a kind of link (documents), tests or stubs (code) or the theme no
  longer zooms back out. Every map has **Reset view** for the whole map, and **All links on** and **All
  links off** (documents, code, Complete Atlas).
- Code opens from every view: a function has **Open in editor** and **Show in folder** (Explorer, the
  file selected), on the code pages and in the Complete Atlas; a module has **Open its folder** (the
  folder its files share). A folder in a project opens in Explorer from a page too.
- **Claude starts with the project's skill.** Claude Code in a terminal starts with `/contextmax-<project>`
  as its first message, which loads the skill. **VS Code with Claude** waits for the project's VS Code
  window (up to 30 s), brings it to the front, and only then opens Claude's chat there with
  `/contextmax-<project>` typed in; before, the chat's link went to whichever VS Code window was in front,
  often another one, and the project's window showed Copilot. If the window does not appear, the window
  says so.
- **Every value says exactly where it is.** A value records its line in the document's text, its page
  (PDFs, from where each page starts; recognised scans too), the heading it stands under and the words
  around it, cut only between words. One citation format everywhere (Ask, values page, documents page,
  `contextmax params`, the skill): *Detailed design · Design · page 12, line 340 · §3.1 PID step*, or
  *Budget.xlsx · Design · Budget!B6* for a cell. In the window, **Show the line** opens the document's
  text at that line, highlighted, with the page marks; a page opened from disk links to the extracted
  text. The validation gate checks that the line a value names shows that value (and a range that runs
  onto the next line, its end there) and that the page holds the line. The value database
  (`params.sqlite`, schema 2) keeps line, page, section, sentence, symbol and where the name came from.
  A scan recognised before this keeps its text and cites lines; **Rebuild everything** recognises it
  again with its pages (the build summary says how many such scans there are).
- **Values are named by their sentence.** Before, a value had a name only when written "Name: value"
  (5% of the values of a folder of papers and books, 22% of a master's project). Now "a settle time of
  12 ms", "the supply voltage shall be 24 V" and "shall keep the gain margin at 6 dB" name their value
  too: two to four words before the value, up to a linking word, never only generic words, never a
  comparison ("a much higher value"), never cut from the words before it ("the speed of the drive
  shaft"). The symbol written with a name is kept beside it ("total energy" with E), values listed after
  a named one share its name ("are 128.3 rad/s and 104.8 rad/s"), and a word a PDF broke over a line is
  joined ("resis-tance"). `label_source` says where each name came from (label, cell, sentence). 50 of
  the new names, drawn at random and judged by hand: 37 right, 6 with the wrong name, 7 not names; the
  rules were then corrected for the patterns those showed, and a second round of 50 is out for judging.
- **The source is the truth, and every answer says how sure it is.** The index is the way in: the skill
  (Claude Code, Copilot, Codex) and the project's `CLAUDE.md` and `AGENTS.md` now say to open the document
  or the code the index points to, at the cited line, read it, answer from it and link it; when the source
  says otherwise than the index, the source wins. Every answer ends with `Confidence: High`, `Medium` or
  `Low` and why, judged on what was read, or says plainly that nothing was found and what was searched.
  A model on this PC gets the same rule, and each value it is given carries the lines of the document or
  code file it comes from, read by ContextMAX itself. The Ask page shows the model's own confidence beside
  ContextMAX's check (are the numbers in the sources they cite, are the cited sources real) and counts the
  lower of the two; when the model is surer than its sources allow, it says so.
- **Try it on a made-up project**: a button on the start screen writes the small motor controller of the
  README's animation (C firmware, VHDL logic, MATLAB models, a Python tool, nine documents that do not
  all agree), opens it with the live drawing on and builds it; pressed again, it opens the same project.
- The release has two downloads: `ContextMAX-<version>-setup.zip`, the program, whose setup.cmd fetches
  Python and the packages, and `ContextMAX-<version>-offline.zip`, everything for a PC without internet.
  `make-offline-installer.cmd` makes both.
- The Ask page's number check reads the answer's claims only, not the model's explanation of its
  confidence after the "Confidence:" line; a Medium confidence is shown in amber, Low in red. The model is
  told never to convert or reinterpret a number or a unit, only to copy them as written.
- **A range is written 1~4.** A dash between two numbers reads as a minus, to a model as much as to a
  person, so every range is written with a tilde: in the value list, on the pages, in what a model is
  given and in the skill (`4–20` from an earlier version still reads as 4~20). A range written with its
  unit on both numbers, `1 cm - 4 cm`, or `from 35 mm to 150 mm`, is one range, not two values.
- **Fewer things read as values that are none.** Left out now: decades ("the 1980s", not 1,980
  seconds), the numbers of figures, tables, equations, sections, examples and algorithms ("Fig. 76.16 A
  mobile robot"), numbered references ("192 A. Smith", "12.45 N.P. Clark"), a unit on the next line
  when a formula follows ("1 / s + 10"), and a unit whose capitals do not match ("a13" is no ampere). A
  unit a PDF put on the next line of running text still counts ("1.2 / m of wingspan", "2 to 3 / cm.").
  Each rule was checked on a random sample of what it leaves out. On the folder of papers and books the
  values went from 16,185 to 11,969 (1,778 references, 203 figure and table numbers, 356 decades, about
  1,900 formula pieces) while the named values went from 878 to 1,326, distinct names from 250 to 604, and
  links for shared values from 22 to 106.
- **Values in the code.** Each code map lists its named numbers (`code\<base>\values.jsonl`): `#define`,
  `const` and `constexpr` in C and C++, numbers set at module or class level in Python, `name = number`
  in MATLAB (struct fields too), constants and generics in VHDL, each with its file, line, comment and
  unit. The unit comes from the name (`TIMEOUT_MS`; `_A`, `_V` and `_S` only beside a word for that
  quantity, so `CHANNEL_A` is no current), the comment (`[ms]`, `in ms`) or the literal (`10 ns`); when
  the name and the comment disagree, the unit is unknown and the row says why. A unit is never guessed.
- **Documents against the code.** A document's value name meets a code name when they say the same
  words (`settle time` and `PID_SETTLE_TIME_MS`; abbreviations such as MAX, FREQ and CLK read out; the
  code may add one word, such as its module), or when the code's comment is that name; a value without a
  name meets a code value with the same number when its sentence says two words of the code's name ("The
  sensor shall be sampled at 2000 Hz" and `SENSOR_SAMPLE_HZ`). Each pair is compared in one unit:
  **match** (a range holds the code's value; "at least" and "at most" are kept), **mismatch**, **unit
  unknown** (the note says whether the numbers agree, or in which unit they would) or **units differ**.
  Several code names that could be meant are all listed as candidates. `documents\links\value-to-code.jsonl`
  holds every pair and the gate recomputes it. The values page has **In the code** with each code value,
  its outcome and **Open in editor**; a document's details list its values in the code; the Complete Atlas
  draws **value in code** lines from a document to the module, red on a mismatch.
- **A model on this PC reads the sources, guided step by step** (`reading.py`). In an editor Claude
  finds a way in, opens the file, reads the passage, follows what it points to and checks it; a local
  model is not good at deciding all that by itself, so ContextMAX holds the procedure and the model only
  reads. ContextMAX finds the ways in (values with their line, every other document that states the same
  value names, the code the index links a value to and the documents it links a code value to, functions,
  passages), opens each file at that place (the section from the heading above to the next, the whole
  function, the sheet's rows; copies and versions of one document once), and has the model read one
  passage at a time, answering in JSON with the exact words it relies on and their line numbers, and what
  the passage points to. Every quote is looked up in the file; one the file does not hold is left out and
  said. What a passage points to (a function, a named number, a table in the same document, another
  document) is read too, up to three. The answer is made from the checked quotes only and cites them;
  nothing relevant read is a plain "not found", said by ContextMAX without asking the model to guess. A
  model that can see (gemma4, qwen3.8; Ollama says which) also gets the PDF pages as pictures, so formulas,
  tables and figures the extracted text garbles are read from the original, and pictures whose file name
  the question says. Every reading runs at temperature 0 with a fixed seed. The Ask page shows what was
  read, step by step, with **Show the line**, **Open document** or **Open in editor** for each passage, the
  checked words of every source, and three confidences: ContextMAX's from what was read and checked, the
  answer's numbers against the words they cite, and the model's own; the lowest counts. It works with every
  model, tool calling or not. On the demo, qwen3-coder 30B read six passages in about 9 s and found the
  test plan's 15 ms against 12 ms everywhere else; gemma4 31B read a thesis with its pages as pictures. The
  window suggests a model for the PC's graphics memory (Qwen 3.8 27B for 20 GB or more,
  smaller Qwen 3 models below), with a button that has Ollama download it in a window of its own, or a link
  to Ollama when it is not installed. Only a model ContextMAX suggests is ever downloaded.
- Builds use the PC's processors. Documents are read, scans recognised (in pieces of four pages, the
  largest scans first), C files and headers read, the document map's searches done (code names, headings
  and values, cited titles), the pages written and the fingerprints checked by worker processes: one per processor thread but one, as many as
  the memory allows, below normal priority so the PC stays quick to use. Word and Excel still open one
  document at a time. A worker writes only its own document's files; the main process writes everything
  shared, in the same order as ever, so the index is the same, byte for byte, with one worker or many
  (`CONTEXTMAX_WORKERS=1` runs as before). Measured on a Ryzen 5 3600 (12 threads): 10,002 documents and
  10,060 code files in 131 s instead of 308 s (reading 105 s to 25 s, the code map 39 s to 25 s, the
  document map 115 s to 48 s, the pages 24 s to 12 s), the same index; the scale demo in 148 s with
  eleven workers and 304 s with one, the same index; a folder of 386 documents with 83 scans (872 pages)
  in 8 minutes with eleven workers and 21 minutes with one, the same index.
- Scans are recognised whole: the limit of 200 pages is gone, and a scan read only in part before is
  read again, whole. Read in pieces, every page reads exactly as it did in one go: on that folder, 385 of
  386 documents came out byte for byte as before, and the 646-page book's first 200 pages too.
- A piece of work whose worker process dies is done again, alone, up to three times; a document that
  kills its process every time is listed as unreadable, with that reason, and the build goes on.
- **Stop the build** in the window stops a build at its next step and keeps what it finished: the
  documents read and the scans recognised so far are saved, and the next build goes on from there.
  Closing the CMD window stops the build the same way, and its log says so; the window says ContextMAX
  was closed, with the log's place.
- The window says, above the build buttons, how the last build ended, what it could not read
  (unreadable documents with their reasons, scans in which no text was found, scans read in part,
  documents still in the cloud), and what changed in the folders since; it marks the button to press:
  **Read documents and build** when something changed or a build did not finish, **Rebuild everything**
  to try again what could not be read.
- The documents page's Network view opens on a large project: it laid out 9,620 documents and their
  links in about 18 s, where it had not finished after 5 minutes. Every link is still drawn as its
  own line; a large network is laid out once and then stands still, hides its lines only while it is
  dragged or zoomed, and starts from a fixed seed, so the same documents give the same picture.
- Document text cache: PDF, Word, RTF, text, Excel and CSV, old Office files through Word and Excel,
  scanned PDFs through text recognition; copies folded by name and size; files in the cloud
  kept pending; incremental, with pruning after a safe write.
- Document map: stages with a recorded reason, revisions folded into one document, links to code by
  distinctive names only, "about a part of the code" kept apart from a link, headings, "shall"
  statements, links by citation (`cites`), document number (`quotes`), shared values (`shares`) and
  the same part of the code (`samepart`).
- Every named value with its source, as a list and as an indexed SQLite database; formula trace and
  row-pairing check on live workbooks.
- A strict validation gate before any page is written, by any build and by `share`.
- Pages: code in bubbles, drafting table, metro lines and zoom levels; documents as a map, a drafting
  table and a network; parameters; connections; light and dark.
- Skill for Claude Code and Copilot: answers in three parts (what the code does, what the documents
  say, and an outcome: Match, Only in documents, Only in code, Mismatch) and one status line.
- `buildinfo.json` with the input and output fingerprints kept apart, and an honest completeness verdict.
- `share` writes a portable copy for colleagues; `selfcheck` writes a verdict to send for help.
- `setup.cmd` installs everything itself, per user and without administrator rights: a private copy
  of the official Python (from nuget.org, checked against a pinned SHA-256; a Python already on the PC
  when there is no internet), the private environment with ContextMAX and its readers, Start menu and
  desktop shortcuts, the `contextmax` command on the PATH (in a folder of its own, so the user's own
  `python` stays first), an entry in Apps & features and `uninstall.cmd`, which keeps the projects.
  `ContextMAX.cmd` runs `setup.cmd` the first time. The window's folder picker is the modern Windows
  dialog, called directly (no tkinter), and folder names in any script work.
- **Ask your AI** on the Home page starts VS Code with Claude's chat, VS Code (Copilot), Claude Code or
  Codex in the project's working folder, with the skill installed for it (Codex too, where it is
  installed); the working folder gets `CLAUDE.md`, `AGENTS.md`, Claude Code's read access to the project's
  folders and a VS Code workspace. **A model on this PC** answers from sources ContextMAX finds in the index
  itself, through Ollama, llama.cpp's server or LM Studio, and only ever asks 127.0.0.1.
- The documents page's **Open document** and **Show in folder** work: the window opens the file, and a page
  opened from the folder uses a `contextmax-open:` link that setup.cmd registers (`--no-links` leaves it
  out). Only documents inside a ContextMAX project are opened, checked as text before anything is touched,
  so a link cannot make Windows contact another computer; a link opens only formats that carry no code.
  **Extracted text** opens in a new tab.
- The window answers only requests addressed to it on this PC (a web page that points its own name at
  127.0.0.1 is refused) and its pages cannot be framed by another site.
- A page whose data held `<!--` (an HTML comment in a Markdown document or a docstring) showed nothing;
  it shows now.
- In the code map's bubbles, a bubble that opens on a double-click carries an arrow going into a box.
- Links to a document from the code and parameters pages, and to a function from the documents page,
  select it again (the page kept only its view in the address).
- `make-offline-installer.cmd` makes a zip that installs ContextMAX on a PC without internet: the same
  Python, every package and ContextMAX itself as wheels pinned by SHA-256, RapidOCR's Cyrillic model and
  a list of the packages' licences; installed once with the network shut off before the zip is written.
- `setup.cmd` also works for user names outside the system's code page (Cyrillic, Chinese), and an update
  while ContextMAX is open moves the old environment aside instead of clearing it under the open window.
- Scanned PDFs are read page by page at 300 dpi, by Windows' text recognition and by RapidOCR, which
  setup.cmd installs: the language, the reader and the way up are chosen per page by how much of the
  text reads as words (Chinese, Japanese, Arabic and Hebrew included); a slanted scan is straightened,
  tables keep their rows and two columns are read in order. On 13 made-up test scans (English, Dutch,
  German, Russian, Chinese, a table, a slanted table, small print, a sparse page, two columns, a mixed
  document, and English and Russian pages on their side) the text matched 99.3% of characters on this
  PC, against 64.9% before. Doubtful pages are counted; a scan that could not be read is not read again
  on every build; documents an earlier version recognised are read again.
- ContextMAX's own names throughout: working folders `catalogue`, `code`, `documents`, `pages` and
  `notes`; build options `--catalogue`, `--documents` and `--full`; most counts named `<thing>_count`;
  `links/between-docs.jsonl`, `hdl-tree.json`, and the value database's tables `sources`, `places` and
  `entries`. `code-guide.md` and `hdl-guide.md` open with an overview table.

Fixed before release:

- Word read no .doc or .rtf file at all: the placeholder password was longer than the 15 characters
  Word accepts, so every Open failed. Word's text now also keeps automatic list and heading numbers
  ("3.1 Control loop"), writes a table as a row per line with tab-separated cells, and turns Word's own
  marks (manual line and page breaks, special hyphens) into plain text. Cached .doc and .rtf text is
  read once more (reader version 3).
- The RTF reader reads `\uN` characters and symbol words (dashes, bullets, quotes).
- VHDL: an `inout` port was recorded as `in` with the type `out ...`; a port without a mode lost the
  first letters of its type (`integer` became `teger`); a type's own closing parenthesis was cut off.
- When the check for Word, Excel and text recognition timed out, the hidden Word or Excel it had
  started stayed running; it is now stopped, as for every other Office step. Why the check did not
  finish is recorded, and an old .doc file left unread gives that reason instead of "this PC does not
  have Word". A scanned PDF whose text recognition failed keeps the reason (`ocr_problem`).
- `build --catalogue` wrote the pages again from the document map on disk without checking it, and
  `share` copied it unchecked; both now run the validation gate first.
- The default rules no longer carry document-type words of one particular organisation.
- `checkup` named the old installer; it now says `setup.cmd`.
- The window refused a request without its token by closing the connection before reading it, which
  Windows can turn into a reset instead of the "not allowed" answer.
- The README names the preview option of `share` as it is: `--dry-run`.
