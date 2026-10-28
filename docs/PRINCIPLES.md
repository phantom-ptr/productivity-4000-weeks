# Four Thousand Weeks, distilled for this app

Source: Oliver Burkeman, *Four Thousand Weeks: Time Management for Mortals* (2021).
Everything below is paraphrase, not quotation. Chapter titles and order are from
memory of the book and have not been re-checked against a copy; flag any slip.

The book's one idea: an average life is about four thousand weeks. "Time
management" as sold is a scheme to fit everything in, which cannot work. The
sane response is to accept the limit, choose a few things, let the rest go,
and stop treating the present as a mere means to the future.

## Chapter outline

**Introduction: In the Long Run, We're All Dead.** Four thousand weeks is the
whole budget. Productivity advice makes the problem worse because it promises
you can get on top of everything.

### Part I: Choosing to Choose

1. **The Limit-Embracing Life.** Before clocks, people worked by task, not by the
   hour. Once time became a resource to "use", it became something to waste,
   and anxiety followed. Treat time as the medium you live in, not a thing you own.
2. **The Efficiency Trap.** Getting faster at tasks raises the bar: an empty inbox
   attracts more email. Convenience removes friction and, with it, meaning.
   Because the supply of demands is endless, the only move is to choose what
   to neglect.
3. **Facing Finitude.** Every yes is a thousand noes. Missing out is not a bug;
   it is what makes a choice a choice. Hence the "joy of missing out".
4. **Becoming a Better Procrastinator.** The skill is creative neglect. Three
   principles: pay yourself first with time (do the thing that matters before
   the day eats you); limit work in progress (about three big things at once,
   and nothing new until one finishes); resist middling priorities (the
   second-tier goals are the dangerous ones because they are attractive enough
   to steal time from the first tier). Also: perfectionism as a way of never
   committing, and "settling" as the mature act of choosing one thing.
5. **The Watermelon Problem.** Attention is your life. Distraction is choosing to
   spend it on things you would not choose if you noticed.
6. **The Intimate Interrupter.** We reach for distraction to escape the discomfort
   of being finite and bad at hard things. More willpower is not the fix;
   tolerating the discomfort is.

### Part II: Beyond Control

7. **We Never Really Have Time.** Plans are thoughts about the future, not
   control over it. Hofstadter's law: things take longer than expected even
   when you expect that. You cannot bank time; you can only be here.
8. **You Are Here.** Using every moment as a step toward a later payoff means
   never arriving. Do some things for their own sake. Notice that every
   ordinary act is one of a finite count.
9. **Rediscovering Rest.** Rest that must be productive is not rest. Leisure
   justified only by recovery is still work. Keep hobbies you are slightly
   embarrassed by; they are the ones with no instrumental excuse.
10. **The Impatience Spiral.** Speed is addictive and makes slowness feel
    unbearable. Accept that things take the time they take.
11. **Staying on the Bus.** Three parts of patience: develop a taste for having
    problems (a life without problems is not on offer); radical incrementalism
    (small daily amounts, and stop while you still want to continue); and
    originality lies on the far side of unoriginality (the Helsinki bus station:
    all routes look the same for the first stops, so stay on yours).
12. **The Loneliness of the Digital Nomad.** Time is worth more when shared. Total
    freedom over your schedule isolates you. Keep time in step with others.
13. **Cosmic Insignificance Therapy.** Your life will not change history, and
    that is a relief: it frees you to live a modestly meaningful one.
14. **The Human Disease.** Five questions to ask yourself (paraphrased):
    where you chase comfort when discomfort is called for; whether you judge
    yourself by impossible standards; where you have not yet accepted who you
    actually are; what you are postponing until you feel ready; and what you
    would do differently if you stopped needing to see results.

**Afterword: Beyond Hope.** Hope that things will one day be under control is
itself a way of not living now. Give it up and act from where you are.

### Appendix: ten tools for embracing finitude

1. **Fixed volume.** Keep an open list (anything goes) and a closed list with a
   hard cap, about ten. Nothing enters the closed list until something leaves.
   Set fixed time boundaries as well.
2. **Serialize.** One big project at a time, finished before the next starts.
3. **Decide in advance what to fail at.** Strategic underachievement: pick the
   areas you will deliberately neglect, so failure there is a choice, not a
   verdict.
4. **Keep a done list.** Record what you completed, not only what remains.
5. **Consolidate your caring.** Pick a few causes and let the rest go.
6. **Boring, single-purpose technology.** Tools that do one thing and do not
   try to keep you.
7. **Novelty in the mundane.** Pay closer attention instead of seeking new stimuli.
8. **Be a researcher in relationships.** Curiosity instead of control.
9. **Instantaneous generosity.** Act on a generous impulse the moment it arrives.
10. **Practice doing nothing.** Sit and resist the urge to act on anything.

## What this means for the app

The app is deliberately a boring, single-purpose tool (tool 6). It has no
accounts, network, telemetry, notifications, streaks, badges, timers or scores.
It never tells you how behind you are.

| Book idea | App feature |
|---|---|
| Fixed volume: open list, capped list (tool 1) | Three capped buckets: **Open** (20 by default, on its own page), **Closed** (10) and **Focus** (3). When a bucket is full, something has to give: you pick which Focus item steps aside, and the last item of a full Closed or Open list moves down a list. |
| Limit work in progress, three big items (ch. 4) | Focus cap defaults to 3. You cannot add a fourth; you must finish or demote one. |
| Pay yourself first (ch. 4) | One Focus item can be marked **first**. It is shown alone, above everything else. |
| Resist middling priorities, decide what to fail at (ch. 4, tool 3) | A **Neglect** shelf. Moving an item there asks for a one-line reason and records it as a deliberate choice, not a failure. |
| Joy of missing out (ch. 3) | Letting go ("retire") is a first-class outcome, dated and in the report. Items that sit in Open for two weeks appear on the Neglect page, where you can renew, move or retire them. |
| Done list (tool 4) | Every completion is stored with its date and shown as **Done today** at the bottom of the Focus page. Nothing is ever deleted from history. |
| Serialize (tool 2) | Optional project tag. The UI notes when more than one project has Focus items. No block, only a note. |
| Rest and atelic activity (ch. 8, 9) | A done entry can be logged with no task behind it and tagged **for its own sake**. The report counts these separately and never scores them. |
| Radical incrementalism, stay on the bus (ch. 11) | No streaks, no counts of consecutive days. A single line under the done list reminds you to stop while you still want to go on. |
| Five questions, cosmic insignificance (ch. 13, 14) | A **weekly review** page shows one of the five questions and the week's done and let-go lists. Answers are stored locally. No reminders. |
| Four thousand weeks (intro) | Optional: enter a birth date and the **lifeline** under the header lights up: weeks lived, a ribbon of your 4,000 weeks, weeks to go. The Weeks page draws every week as a dot. Stored only on your machine. Blank by default. |
| Efficiency trap, impatience (ch. 2, 10) | No time estimates, no due dates by default, no timers, no pomodoro. |
| Year-end report (your request) | Per year and per month: completed, let go, neglected on purpose, for-its-own-sake entries, by project; age of items at completion; the review answers you wrote. Exportable as a single self-contained file. |

Anti-features, on purpose: no sync, no login, no cloud, no analytics, no
notifications, no gamification, no AI. The data file is yours and readable
with any text editor.
