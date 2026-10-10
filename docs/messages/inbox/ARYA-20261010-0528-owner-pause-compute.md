ID: ARYA-20261010-0528-owner-pause-compute
Created: 2026-10-10T05:28:20Z
Sender: Arya
Type: INSTRUCTION

LATEST OWNER DIRECTION supersedespriorcontinue/0512acceptance expansion: Michael says we don't need to spend any more compute on DealSniffer and asks to pause; he reports constrainedClaudeusage and shifting subscription toOpenAI/dot. Checkpoint and safelypause DealSniffer NEW development/modeldispatch now. Do not startF53 or anotherfeatureworker ifnotstarted. If a boundedworker isalreadyinflight, preservevalidwork/checkpoint it atsafe boundary thenstop; no addedtests/rewrites beyondnecessarysafehandoff. No destructivekill/discard ofuncommittedwork.

Existingowningcoordinator must preventqueuedfeature/instructionmessagesfromstartingnew modelwork whilepaused. Preserve code,data,receipts,queueandinstalledinfrastructure. Zero-modelread-onlyheartbeat/transport mayremain onlyif itcannotlaunchmodeljobs; don'tallow thewatcher toconsumeexpensivecoordinationafterthispause. No newpersistenceunitinstall orpermissionchange. Record PAUSED_BY_OWNER with exactcheckpointSHA, unfinishedwork, runningworker disposition and resumecommand/conditions. ACKpause promptly and publishfinalreconciliationonceactualdispatchstopped. Do not claimlocalprocessstop solelyfromGitHubsilence.

CAOSCare continuesits separatelyauthorized overnightnonvoicework; Desktop remainsalready paused. This instruction isDealSniffer/MBOSonly. ParentwillstopitsroutineMBOSpolling afterpauseverified andretainread-onlylaterchecks. No liveUIreload. Userwantsagent-firstrealdealresearchtomorrow, notfurtherappfeaturecompute.