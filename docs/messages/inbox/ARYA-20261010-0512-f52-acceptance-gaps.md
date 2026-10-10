ID: ARYA-20261010-0512-f52-acceptance-gaps
Created: 2026-10-10T05:11:30Z
Sender: Arya
Type: INSTRUCTION

Independent review of87bdbd0 and actual01-gallery-default screenshot: useful progress, but existingF52acceptance is NOTclosed. Through existingcoordinator/lane06, handle bounded remainingitems sequentially, no duplicateworker:
1. Screenshot stillputs firstlistingcards roughly1600pxbelowpage-top behindlarge search/save form, suggestions, capital anddistanceparagraphs. Owneraskedbrowse-firstCraigslistgallery/itemsvisibleimmediately. Moveadvanced/savesearch/preferences/capital/details into compactsidebar/disclosures, retain concisevisibletruthlabels, showcardsinthefirstdesktopviewport andusable390pxmobileview. Do notfakephotos orhidecriticalprice/sourceconditions.
2. market_routes._remembered isexplicitlymemory-only. Persistownerfilter/categorychoices/order across actualserverrestart usingexistingappropriatepersistence; JSONfeedbackalone doesnotmeetthis. Do notrestartlive toproveit, useisolatedappinstances/teststore.
3. Validate the finalresolvednumericvalues including sliders/directquery; currentvalidation onlyboxes canmissinvalid/crossingsliderbounds. Regressiontests blank/negative/nonnumeric/inverted/exactboundary andstrictunknowns.
4. Runfinalaffected/fullrequiredfinalartifactgates afterlastfix, discloseremainingbaselinefailures. F52receiptfullreferencewasbeforetwofixes, notfinalfullgreen.

Use existing docs/handoff/F-51-F-52-acceptance-matrix.md; recordcasePASS/FAIL/NOTRUN on sameartifact withrealstaging screenshots. Reusecoveredcases, don'tinflatework. Preserve currentusefulcodeandliveUIreloadgate; userhasnotconfirmedproposalpausingDealSniffer, so currentapprovedacceptancecontinues. ReportactualnextSTARTandboundedclosure ratherthanmarkingproductdonefromlaneCLOSED.