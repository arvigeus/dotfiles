import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtCore
import Quickshell
import "../../ui"
import "../movies"
import "../movies/Catalogue.js" as Catalogue

Item {
    id: root
    objectName: "booksBrowser"
    property var host
    property var books: []
    property var selected: ({})
    property bool active: false
    property var toolbarTarget: null
    property var backdropTarget: null
    property real toolbarHeight: 46
    property var initialFocus: searchOpen ? search : gridMode ? grid : rail
    property bool initialized: false
    property bool needsBrowse: false
    property bool needsLocalRefresh: false
    function fontSize(value) { return Math.round(value * MovieStyle.fontSize / 14); }
    property var personal: ({favorite: false})
    property var filters: ({})
    property string nextPage: ""
    property string error: ""
    property string detailError: ""
    property bool loading: true
    property bool detailLoading: false
    property bool favorites: false
    property bool localMode: false
    property var localFiles: []
    property bool searchOpen: false
    property bool filtersOpen: false
    property bool gridMode: false
    property int browseGeneration: 0
    property int selectionGeneration: 0
    property int authorGeneration: 0
    property int editionsGeneration: 0
    property string tab: "overview"
    property var author: ({})
    property var authorDetails: ({})
    property var authorWorks: []
    property string authorNext: ""
    property string authorError: ""
    property bool authorLoading: false
    property var editions: []
    property string editionsNext: ""
    property string editionsError: ""
    property bool editionsLoading: false
    property var providerNames: []
    property var onlineOffers: []
    property bool offersChecked: false
    property bool offersLoading: false
    property bool providerResolving: false
    property int offersGeneration: 0
    property int offerIndex: 0
    property string offersError: ""
    property var findOffers: []
    property bool findOffersLoading: false
    property string findOffersError: ""
    property string findOffersInfo: ""
    property int findGeneration: 0
    property bool updatingCatalogue: false
    readonly property bool workSelected: !!selected.id && selected.source !== "provider" && /^OL\d+W$/.test(String(selected.id))
    readonly property var downloadJobs: service.jobs
    readonly property bool titleLoading: detailLoading
    readonly property bool findLoading: tab === "torrent" && (torrentFind.connectionLoading
        || torrentFind.searching || torrentFind.extraSearching || torrentFind.reviewLoading
        || torrentFind.inspectLoading || torrentFind.moreLoading || torrentFind.startLoading
        || torrentFind.launchPending || torrentFind.tracksLoading)
    readonly property bool busy: loading || detailLoading || offersLoading || providerResolving
        || findOffersLoading || (tab === "author" && authorLoading)
        || (tab === "editions" && editionsLoading) || findLoading
        || localService.pendingDownloads > 0 || localService.pendingChanges > 0
        || service.activeJobCount > 0 || (tab === "scan" && (scanPanel.scanning || scanPanel.matching))
    readonly property string readingAction: selected.ebookAccess === "public" ? "Read on Open Library" : selected.ebookAccess === "borrowable" ? "Borrow on Open Library" : selected.ebookAccess === "printdisabled" ? "Preview on Open Library" : ""

    ListModel { id: catalogue }
    ListModel { id: authorCatalogue }
    Settings {
        id: preferences
        location: "file://" + (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/quickshell/desktop/spaces/books/books-ui.ini"
    }
    BooksService {
        id: service
        onFailed: message => { root.error = message; root.loading = false; }
        onJobStartFailed: message => { root.findOffersError = message; activity.notify(message, true); }
        onJobFinished: job => {
            if (job.state === "finished") { root.refreshLocalLibrary(); activity.notify("Book downloaded to " + job.result.path, false); }
            else if (job.error) activity.notify(job.error, job.state === "failed");
        }
    }
    TorrentService {
        id: localService; spaceId: "books"; monitorJobs: true; foreground: root.active; monitorKind: "book"
        onLibraryChanged: root.refreshLocalLibrary()
    }
    OperationCenter {
        id: activity; parent: root; jobs: service.jobs; notificationTitle: "Books"
        onCancelRequested: jobId => service.cancelJob(jobId)
        onActionRequested: job => service.retryJob(job.job_id)
    }
    function refreshLocalLibrary() {
        if (!active) { needsLocalRefresh = true; return; }
        needsLocalRefresh = false;
        const generation = selectionGeneration;
        if (selected.id) service.request("local_files", {title:Object.assign({}, selected, {kind:"book"})}, (result, failure) => {
            if (generation === selectionGeneration && !failure) localFiles = result;
        });
        if (localMode) browse(false, false);
    }

    ArtworkCache { id: bookArt; spaceId: "books" }
    Rectangle {
        objectName: "booksBackground"
        parent: root.backdropTarget || root
        anchors.fill: parent
        z: root.backdropTarget ? 0 : -1
        visible: root.active
        color: "#000000"
    }

    function activate() { if (active) (gridMode ? grid : rail).forceActiveFocus(); }
    function sameBook(a, b) { return !!(a && b && a.id && b.id && a.id === b.id); }
    function updateCatalogue(items, append) {
        updatingCatalogue = true;
        books = Catalogue.update(catalogue, books, items, append);
        updatingCatalogue = false;
    }
    function updateAuthorWorks(items, append) {
        authorWorks = Catalogue.update(authorCatalogue, authorWorks, items, append);
    }
    function updateBook(book) {
        if (!book || !book.id) return;
        const index = books.findIndex(item => item.id === book.id);
        if (index >= 0) {
            const next = books.slice(); next[index] = book; books = next;
            const row = Array.from({length: catalogue.count}, (_, i) => catalogue.get(i)).findIndex(item => item.key === book.id);
            if (row >= 0) catalogue.setProperty(row, "payload", JSON.stringify(book));
        }
        if (sameBook(selected, book)) selected = book;
    }
    function clearSelection() {
        ++selectionGeneration;
        resetOffers(); resetFindOffers();
        detailDelay.stop();
        selected = ({}); personal = ({favorite: false}); detailLoading = false; detailError = "";
    }
    function chooseFirstIfNeeded() {
        if (books.length && !books.some(book => sameBook(book, selected))) selectBook(books[0]);
        else if (!books.length) clearSelection();
    }
    function browse(append, force) {
        if (!active) { needsBrowse = true; return; }
        needsBrowse = false;
        if (localMode) {
            const generation = ++browseGeneration;
            loading = true; error = ""; nextPage = "";
            service.request("local_list", {kind:"book"}, (result, failure) => {
                if (generation !== browseGeneration) return;
                loading = false;
                if (failure) { error = failure; return; }
                const query = search.text.trim().toLowerCase();
                updateCatalogue(result.filter(book => !query || [book.title, ...(book.authors || []).map(author => author.name)].join(" ").toLowerCase().includes(query)), false);
                chooseFirstIfNeeded();
            });
            return;
        }
        if (append && (loading || !nextPage)) return;
        const offset = append ? Number(nextPage) : 0;
        const generation = ++browseGeneration;
        const args = {query: search.text, filters: filters, favorites: favorites, offset: offset, refresh: !!force};
        loading = true; error = "";
        if (!append && !favorites) service.request("snapshot", args, (result, failure) => {
            // A late snapshot must not replace the live page it was meant to precede.
            if (generation !== browseGeneration || !loading || failure || !result) return;
            updateCatalogue(result.items || [], false);
            nextPage = result.next || "";
            chooseFirstIfNeeded();
            if (result.warning) error = result.warning;
        });
        service.request("browse", args, (result, failure) => {
            if (generation !== browseGeneration) return;
            loading = false;
            if (failure) { error = failure; return; }
            if (!result) { error = "No book results were returned."; return; }
            updateCatalogue(result.items || [], append);
            nextPage = result.next && result.next !== String(offset) ? result.next : "";
            pagination.restart();
            if (result.warning) error = result.warning;
            if (!append) chooseFirstIfNeeded();
        });
    }
    function selectBook(book) {
        if (!book || !book.id) return;
        if (sameBook(book, selected)) { if (tab === "author") tab = "overview"; return; }
        const generation = ++selectionGeneration;
        resetOffers(); resetFindOffers();
        ++authorGeneration; ++editionsGeneration;
        detailDelay.stop();
        selected = book; personal = ({favorite: !!book.favorite});
        localFiles = [];
        detailLoading = workSelected; detailError = ""; tab = "overview";
        author = ({}); authorDetails = ({}); authorWorks = []; authorCatalogue.clear(); authorNext = ""; authorError = ""; authorLoading = false;
        editions = []; editionsNext = ""; editionsError = ""; editionsLoading = false;
        if (workSelected) service.request("personal", {book: book}, (result, failure) => {
            if (generation === selectionGeneration && !failure && result) personal = result;
        });
        service.request("local_files", {title:Object.assign({}, book, {kind:"book"})}, (result, failure) => {
            if (generation === selectionGeneration && !failure) localFiles = result;
        });
        if (workSelected && active) detailDelay.restart();
    }
    Timer {
        id: detailDelay
        interval: 170
        onTriggered: {
            if (!root.active || !root.workSelected) return;
            const generation = root.selectionGeneration;
            service.request("details", {book: root.selected}, (result, failure) => {
                if (generation !== root.selectionGeneration) return;
                root.detailLoading = false;
                if (failure) root.detailError = failure;
                else if (result) {
                    root.selected = Object.assign({}, root.selected, result);
                    root.updateBook(root.selected);
                    if (result.warning) root.detailError = result.warning;
                }
            });
        }
    }
    function refreshBook() {
        if (!workSelected) return;
        const generation = ++selectionGeneration;
        resetOffers();
        detailLoading = true; detailError = "";
        service.request("details", {book: selected, refresh: true}, (result, failure) => {
            if (generation !== selectionGeneration) return;
            detailLoading = false;
            if (failure) detailError = failure;
            else if (result) { selected = Object.assign({}, selected, result); updateBook(selected); if (result.warning) detailError = result.warning; }
        });
    }
    function saveFavorite(value) {
        if (!workSelected) return;
        const generation = selectionGeneration;
        const updated = Object.assign({}, selected, {favorite: !!value});
        selected = updated; personal = ({favorite: !!value}); updateBook(updated);
        service.request("save", {book: updated, favorite: !!value}, (result, failure) => {
            if (generation !== selectionGeneration) return;
            if (failure) { personal = ({favorite: !value}); selected = Object.assign({}, selected, {favorite: !value}); updateBook(selected); detailError = failure; }
            else if (result) personal = result;
            if (root.favorites && !value) root.browse(false);
        });
    }
    function showAuthor(person) {
        if (!person || !person.id) return;
        const generation = ++authorGeneration;
        author = Object.assign({}, person); authorDetails = ({name: person.name || "Unknown author"});
        authorWorks = []; authorCatalogue.clear(); authorNext = ""; authorError = ""; authorLoading = true; tab = "author";
        service.request("authorDetails", {author: author}, (result, failure) => {
            if (generation !== authorGeneration) return;
            if (failure) authorError = failure;
            else if (result) { authorDetails = result; if (result.warning) authorError = result.warning; }
        });
        loadAuthorWorks(false, generation);
    }
    function loadAuthorWorks(append, ownerGeneration) {
        if (authorLoading && append) return;
        const requested = append ? authorNext : "0";
        const generation = ownerGeneration === undefined ? authorGeneration : ownerGeneration;
        const offset = append ? Number(requested) : 0;
        authorLoading = true;
        service.request("authorWorks", {author: author, offset: offset}, (result, failure) => {
            if (generation !== authorGeneration) return;
            authorLoading = false;
            if (failure) { authorError = failure; return; }
            updateAuthorWorks(result.items || [], append);
            authorNext = result.next || "";
            if (result.warning) authorError = result.warning;
        });
    }
    function loadEditions(append) {
        if (!workSelected || (append && (editionsLoading || !editionsNext))) return;
        const generation = ++editionsGeneration;
        const offset = append ? Number(editionsNext) : 0;
        editionsLoading = true; editionsError = "";
        service.request("editions", {book: selected, offset: offset}, (result, failure) => {
            if (generation !== editionsGeneration) return;
            editionsLoading = false;
            if (failure) { editionsError = failure; return; }
            const byId = new Map((append ? editions : []).map(edition => [edition.id, edition]));
            for (const edition of result.items || []) byId.set(edition.id, edition);
            editions = Array.from(byId.values());
            editionsNext = result.next || "";
            if (result.warning) editionsError = result.warning;
        });
    }
    function maybeLoadMore() {
        if (!active || loading || error || !nextPage || favorites || tab === "author") return;
        const nearEnd = gridMode
            ? grid.contentY + grid.height >= grid.contentHeight - grid.cellHeight * 2
            : (rail.contentX > rail.originX || rail.currentIndex >= books.length - 5) && rail.contentX + rail.width >= rail.contentWidth - rail.width * 0.5;
        if (nearEnd) browse(true, false);
    }
    function languageLabel(code) {
        const known = {eng:"English", spa:"Spanish", fre:"French", fra:"French", ger:"German", deu:"German", ita:"Italian", por:"Portuguese", jpn:"Japanese", chi:"Chinese", zho:"Chinese", rus:"Russian", ara:"Arabic", hin:"Hindi", kor:"Korean", vie:"Vietnamese", dut:"Dutch", nld:"Dutch", swe:"Swedish", nor:"Norwegian", dan:"Danish", fin:"Finnish", pol:"Polish", heb:"Hebrew", tur:"Turkish", ind:"Indonesian", cat:"Catalan", lat:"Latin", grc:"Ancient Greek", gre:"Greek"};
        return known[code] || code.toUpperCase();
    }
    function effectiveSortIndex() {
        const sorts = ["trending", "relevance", "newest", "oldest"];
        const saved = sorts.indexOf(root.filters.sort || "");
        return saved >= 0 ? saved : (search.text.trim().length ? 1 : 0);
    }

    function resetOffers() {
        ++offersGeneration;
        onlineOffers = []; offersChecked = false; offersLoading = false;
        providerResolving = false; offerIndex = 0; offersError = "";
        onlineButton.popup.close();
    }
    function offerLabel(offer) {
        return [offer.provider, offer.format || "Unknown format", offer.language,
                offer.size_bytes !== undefined && offer.size_bytes !== null ? torrentFind.sizeLabel(offer.size_bytes) : offer.size || ""].filter(Boolean).join(" · ");
    }
    function readOnline(index) {
        if (!workSelected || offersLoading || providerResolving) return;
        if (offersChecked) { if (onlineOffers[index]) resolveOffer(onlineOffers[index]); return; }
        const generation = ++offersGeneration;
        offersLoading = true; offersError = "";
        service.request("providerOffers", {book: selected}, (result, failure) => {
            if (generation !== offersGeneration) return;
            offersLoading = false;
            if (failure) { offersError = failure; return; }
            onlineOffers = result.items || []; offersChecked = true; offerIndex = 0;
            offersError = result.warning || (onlineOffers.length ? "" : "No matching online offers found.");
            if (onlineOffers.length === 1) resolveOffer(onlineOffers[0]);
            else if (onlineOffers.length > 1 && active) Qt.callLater(() => { if (active && generation === offersGeneration) onlineButton.popup.open(); });
        }, 0);
    }
    function resolveOffer(offer) {
        if (!offer || offer.source !== "provider" || providerResolving) return;
        const generation = offersGeneration;
        providerResolving = true;
        offersError = "";
        service.request("providerResolve", {provider: offer.provider, ref: offer.ref, purpose:"read"}, (result, failure) => {
            if (generation !== offersGeneration) return;
            providerResolving = false;
            if (failure) { offersError = failure; return; }
            if (active) Browser.open(result.url, "books", "", root.host);
        });
    }
    function downloadOffer(offer) {
        findOffersError = "";
        service.startJob("providerDownload", {title:offer.title, offer:offer, book:selected});
        activity.showActivity();
    }
    function resetFindOffers() {
        ++findGeneration;
        findOffers = []; findOffersLoading = false; findOffersError = ""; findOffersInfo = "";
    }
    function searchProviders(query) {
        const generation = ++findGeneration;
        findOffers = []; findOffersLoading = true; findOffersError = ""; findOffersInfo = "";
        service.request("providerSearch", {query: query, page: 0, limit: 10}, (result, failure) => {
            if (generation !== findGeneration) return;
            findOffersLoading = false;
            if (failure) { findOffersError = failure; return; }
            findOffers = result.items || []; findOffersError = result.warning || "";
            if (!findOffers.length && !findOffersError) findOffersInfo = "No results from configured Books providers.";
        }, 0);
    }

    function dismissTransient() {
        if (activity.visible) { activity.close(); return true; }
        if (onlineButton.popup.visible) { onlineButton.popup.close(); return true; }
        if (sortFilter.popup.visible) { sortFilter.popup.close(); return true; }
        if (torrentFind.dismissTransient()) return true;
        if (filtersOpen) { filtersOpen = false; return true; }
        if (search.text) { search.clear(); return true; }
        if (searchOpen) { searchOpen = false; activate(); return true; }
        if (tab !== "overview") { tab = "overview"; return true; }
        return false;
    }
    onActiveChanged: {
        if (!active) {
            if (searchDelay.running) needsBrowse = true;
            pagination.stop(); searchDelay.stop(); detailDelay.stop();
            activity.close(); onlineButton.popup.close(); sortFilter.popup.close();
        } else if (initialized) {
            if (needsLocalRefresh) refreshLocalLibrary();
            if (needsBrowse) browse(false, false);
            if (detailLoading) detailDelay.restart();
            pagination.restart(); Qt.callLater(activate);
        }
    }
    Component.onCompleted: {
        service.request("init", {}, (result, failure) => { if (failure) error = failure; else providerNames = result.providers || []; });
        gridMode = preferences.value("catalogue/grid", false);
        service.request("local_list", {kind:"book"}, (result, failure) => {
            localMode = !failure && !!result && result.length > 0;
            initialized = true;
            browse(false, false);
        });
    }
    onGridModeChanged: { activate(); if (active) pagination.restart(); }
    Timer { id: pagination; interval: 120; onTriggered: root.maybeLoadMore() }
    Timer { id: searchDelay; interval: 350; onTriggered: root.browse(false, false) }

    RowLayout {
        objectName: "booksToolbar"
        parent: root.toolbarTarget || root
        width: parent.width; height: root.toolbarHeight
        visible: root.active
        spacing: 8
            MovieButton { iconName: "folder-open"; text: "Local"; highlighted: root.localMode; onClicked: { root.localMode = true; root.favorites = false; root.browse(false, false); } }
            MovieButton { iconName: "globe"; text: "Discover"; highlighted: !root.localMode && !root.favorites; onClicked: { root.localMode = false; root.favorites = false; root.browse(false, false); } }
            MovieButton { iconName: "star"; text: "Favorites"; highlighted: !root.localMode && root.favorites; onClicked: { root.localMode = false; root.favorites = true; root.browse(false, false); } }
            MovieButton { objectName: "booksScanButton"; iconName: "file-search-corner"; text: "Scan"; onClicked: root.tab = root.tab === "scan" ? "overview" : "scan" }
            MovieButton { iconName: "download"; text: service.activeJobCount ? "Transfers (" + service.activeJobCount + ")" : "Activity"; enabled: activity.hasActivity; onClicked: activity.showActivity() }
            Item { Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 0 }
            Flickable {
                id: inlineFilters; objectName: "inlineFilters"
                visible: root.filtersOpen && !root.favorites && !root.localMode
                Layout.fillWidth: true; Layout.preferredWidth: filterFields.implicitWidth
                Layout.minimumWidth: 110; Layout.maximumWidth: filterFields.implicitWidth
                Layout.preferredHeight: 46
                clip: true; contentWidth: filterFields.implicitWidth; contentHeight: height
                flickableDirection: Flickable.HorizontalFlick
                WheelScroll { view: inlineFilters; orientation: Qt.Horizontal; verticalToHorizontal: true }
                ScrollBar.horizontal: MovieScrollBar {}
                Row {
                    id: filterFields; spacing: 8
                    MovieInput { id: subjectFilter; width: 170; placeholderText: "Subject"; Accessible.name: "Filter by subject" }
                    MovieInput { id: languageFilter; width: 105; placeholderText: "Language · eng"; maximumLength: 3; Accessible.name: "Filter by language code" }
                    MovieChoice { id: sortFilter; width: 138; model: ["Trending", "Relevance", "Newest first", "Oldest first"]; Accessible.name: "Sort books" }
                    MovieInput {
                        id: minYear; width: 84; placeholderText: "From year"
                        validator: IntValidator { bottom: 1000; top: 2200 }
                        Accessible.name: "First published from year"
                    }
                    MovieInput {
                        id: maxYear; width: 84; placeholderText: "To year"
                        validator: IntValidator { bottom: 1000; top: 2200 }
                        Accessible.name: "First published through year"
                    }
                    MovieButton { text: "Apply"; onClicked: { root.filters = {subject:subjectFilter.text,language:languageFilter.text,sort:["trending","relevance","newest","oldest"][sortFilter.currentIndex],minYear:minYear.text,maxYear:maxYear.text}; root.browse(false, false); } }
                    MovieButton { text: "Reset"; onClicked: { subjectFilter.clear(); languageFilter.clear(); root.filters=({}); sortFilter.currentIndex=root.effectiveSortIndex(); minYear.clear(); maxYear.clear(); root.browse(false, false); } }
                }
            }
            MovieInput {
                id: search; objectName: "bookSearch"; rightPadding: 42; visible: root.searchOpen
                Layout.preferredWidth: Math.min(320, root.width * 0.30)
                placeholderText: "Search books, authors, ISBNs…"
                Accessible.name: "Search books, authors, and ISBNs"
                onTextChanged: searchDelay.restart()
                MovieIconButton { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: 36; height: 36; visible: search.text.length > 0; iconName: "x"; text: "Clear book search"; onClicked: { search.clear(); search.forceActiveFocus(); } }
                onAccepted: { searchDelay.stop(); root.browse(false, false); }
            }
            Item {
                Layout.minimumWidth: 28; Layout.maximumWidth: 28; Layout.preferredHeight: 28
                ActivityIndicator {
                        anchors.fill: parent; active: root.active; spinnerName: "booksLoadingIndicator"
                    jobs: service.jobs.concat(localService.jobs)
                    tasks: [
                        task(root.loading, "browse", "Loading books…"),
                        task(root.detailLoading, "details", "Loading book details…"),
                        task(root.offersLoading || root.findOffersLoading, "offers", "Finding book offers…"),
                        task(root.providerResolving, "provider", "Opening book provider…"),
                        task(root.tab === "author" && root.authorLoading, "author", "Loading author…"),
                        task(root.tab === "editions" && root.editionsLoading, "editions", "Loading editions…"),
                        task(root.findLoading, "find", "Searching downloads…"),
                        task(localService.pendingDownloads > 0, "download", "Downloading book…"),
                        task(localService.pendingChanges > 0, "library", "Updating local library…"),
                        task(service.startingJobs > 0, "queue", "Queuing download…"),
                        task(root.tab === "scan" && (scanPanel.scanning || scanPanel.matching), "scan", "Scanning local books…")
                    ]
                }
            }
            MovieIconButton { objectName: "searchButton"; Layout.minimumWidth: 42; Layout.maximumWidth: 42; highlighted: root.searchOpen; iconName: "search"; text: root.searchOpen ? "Close book search" : "Search books"; onClicked: { root.searchOpen = !root.searchOpen; if (root.searchOpen) search.forceActiveFocus(); else search.text = ""; } }
            MovieIconButton { objectName: "filtersButton"; Layout.minimumWidth: 42; Layout.maximumWidth: 42; iconName: "sliders-horizontal"; text: "Book filters"; enabled: !root.favorites && !root.localMode; highlighted: root.filtersOpen; onClicked: { root.filtersOpen = !root.filtersOpen; if (root.filtersOpen) sortFilter.currentIndex = root.effectiveSortIndex(); } }
            MovieIconButton { objectName: "layoutButton"; Layout.minimumWidth: 42; Layout.maximumWidth: 42; iconName: root.gridMode ? "panels-top-left" : "layout-grid"; text: root.gridMode ? "Show cover rail" : "Show cover grid"; onClicked: { root.gridMode = !root.gridMode; preferences.setValue("catalogue/grid", root.gridMode); } }
        }

    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        RowLayout {
            visible: !!root.error; Layout.fillWidth: true
            MovieText { text: root.error; color: MovieStyle.danger; Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2 }
            MovieButton { text: "Retry"; onClicked: root.browse(false, true) }
        }
        Item {
            id: content; Layout.fillWidth: true; Layout.fillHeight: true
            GridView {
                id: grid; objectName: "catalogueGrid"; visible: root.gridMode && root.tab !== "scan"
                x: 0; y: 0; width: parent.width * 0.51; height: parent.height
                clip: true; model: catalogue
                cellWidth: Math.floor(width / Math.max(2, Math.floor(width / 155))); cellHeight: cellWidth * 1.5 + 48
                activeFocusOnTab: true; keyNavigationEnabled: true; keyNavigationWraps: false
                delegate: BookCard {
                    cacheService: bookArt
                    required property string payload
                    readonly property var modelData: JSON.parse(payload)
                    required property int index
                    width: grid.cellWidth - 8; height: grid.cellHeight - 8; book: modelData
                    highlighted: root.sameBook(root.selected, modelData)
                    onClicked: { grid.forceActiveFocus(); grid.currentIndex = index; root.selectBook(modelData); }
                }
                onCurrentItemChanged: if (!root.updatingCatalogue && activeFocus && currentItem && !root.sameBook(currentItem.book, root.selected)) root.selectBook(currentItem.book)
                Keys.onReturnPressed: if (currentItem) root.selectBook(currentItem.book)
                Keys.onEnterPressed: if (currentItem) root.selectBook(currentItem.book)
                WheelScroll { objectName: "gridWheel"; view: grid; wheelStep: Math.max(360, grid.cellHeight * 1.25) }
                onContentYChanged: pagination.restart()
                ScrollBar.vertical: MovieScrollBar {}
            }
            ColumnLayout {
                id: detail
                x: root.gridMode ? parent.width * 0.55 : 16
                y: 0
                width: root.gridMode ? parent.width * 0.45 : Math.min(parent.width * 0.7, 1000)
                height: root.gridMode ? parent.height : parent.height - Math.min(300, parent.height * 0.34) - 16
                visible: !!root.selected.id && root.tab !== "author" && root.tab !== "scan"
                spacing: 8
                ColumnLayout {
                    id: detailText
                    Layout.fillWidth: true; spacing: 10
                    MovieText { Layout.fillWidth: true; text: root.selected.title || ""; font.family: MovieStyle.fontFamily; font.pixelSize: root.fontSize(Math.min(58, detail.width / 12)); font.bold: true; wrapMode: Text.Wrap; maximumLineCount: 3 }
                    Flow {
                        Layout.fillWidth: true; spacing: 3
                        Repeater {
                            model: root.selected.authors || []
                            MovieButton { required property var modelData; objectName: modelData.id ? "authorLink-" + modelData.id : ""; text: modelData.name || "Unknown author"; enabled: !!modelData.id; Accessible.name: "Open author " + text; onClicked: root.showAuthor(modelData) }
                        }
                        MovieText { visible: !(root.selected.authors || []).length; text: "Author unknown"; color: MovieStyle.muted }
                    }
                    MovieText {
                        Layout.fillWidth: true; color: MovieStyle.muted; wrapMode: Text.Wrap; maximumLineCount: 2
                        text: [root.selected.firstPublishYear || "", root.selected.editionCount ? root.selected.editionCount + " editions" : "", root.selected.languages && root.selected.languages.length ? root.selected.languages.slice(0,3).map(root.languageLabel).join(" / ") : ""].filter(Boolean).join("   ·   ")
                    }
                    MovieText {
                        Layout.fillWidth: true; color: MovieStyle.muted; visible: !!root.selected.ratingCount
                        text: root.selected.ratingAverage !== null && root.selected.ratingAverage !== undefined ? root.selected.ratingAverage.toFixed(1) + " / 5   ·   " + Number(root.selected.ratingCount || 0).toLocaleString() + " ratings" : Number(root.selected.ratingCount || 0).toLocaleString() + " ratings"
                    }
                    Flow {
                        Layout.fillWidth: true; spacing: 6
                        MovieButton { objectName: "openLocalBook"; visible: root.localFiles.length > 0; iconName: "folder-open"; text: "Open local book"; onClicked: External.launch(["xdg-open", root.localFiles[0].path], root.host) }
                        SplitButton {
                            id: onlineButton; objectName: "readOnlineButton"
                            visible: root.workSelected && root.providerNames.length > 0
                            text: "Read online"; iconName: "book-open"
                            showLoading: false
                            busy: root.offersLoading || root.providerResolving
                            enabled: !busy && (!root.offersChecked || root.onlineOffers.length > 0)
                            options: root.onlineOffers.map(root.offerLabel); currentIndex: root.offerIndex
                            onTriggered: index => { root.offerIndex = index; root.readOnline(index); }
                        }
                        MovieButton {
                            objectName: "openLibraryButton"
                            visible: root.workSelected
                            iconName: "book-open"
                            text: root.readingAction || "Open Library"
                            Accessible.name: text
                            onClicked: Browser.open("https://openlibrary.org/works/" + root.selected.id, "books", "", root.host)
                        }
                        MovieIconButton { objectName: "favoriteButton"; highlighted: root.personal.favorite; visible: root.workSelected; iconName: root.personal.favorite ? "star-filled" : "star"; text: root.personal.favorite ? "Remove from Favorites" : "Add to Favorites"; onClicked: root.saveFavorite(!root.personal.favorite) }
                        MovieIconButton { visible: root.workSelected; iconName: "refresh-cw"; text: "Refresh book details"; onClicked: root.refreshBook() }
                    }
                    Flow {
                        Layout.fillWidth: true; spacing: 2
                        MovieTab { text: "Overview"; highlighted: root.tab === "overview"; onClicked: root.tab = "overview" }
                        MovieTab { objectName: "editionsTab"; visible: root.workSelected; text: "Editions"; highlighted: root.tab === "editions"; onClicked: { root.tab = "editions"; if (!root.editions.length) root.loadEditions(false); } }
                        MovieTab { text: "Find"; highlighted: root.tab === "torrent"; onClicked: root.tab = "torrent" }
                    }
                }
                RowLayout {
                    visible: !!root.detailError; Layout.fillWidth: true
                    MovieText { text: root.detailError; color: MovieStyle.danger; Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2 }
                    MovieButton { text: "Retry details"; onClicked: root.refreshBook() }
                }
                MovieText { visible: !!root.offersError; Layout.fillWidth: true; text: root.offersError; color: MovieStyle.muted; wrapMode: Text.Wrap; maximumLineCount: 2 }
                ScrollArea {
                    id: overview; visible: root.tab === "overview"
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: overview.availableWidth
                        spacing: 12
                        MovieText {
                            objectName: "bookDescription"; Layout.fillWidth: true
                            text: root.selected.description || root.selected.first_sentence || (root.detailLoading ? "Loading synopsis…" : "No synopsis available.")
                            wrapMode: Text.Wrap; font.pixelSize: root.fontSize(17)
                        }
                        Flow {
                            Layout.fillWidth: true; spacing: 5; visible: (root.selected.subjects || []).length > 0
                            Repeater {
                                model: (root.selected.subjects || []).slice(0, 10)
                                MovieButton {
                                    required property string modelData
                                    text: modelData
                                    Accessible.name: "Filter by subject " + modelData
                                    onClicked: {
                                        root.filters = Object.assign({}, root.filters, {subject: modelData});
                                        subjectFilter.text = modelData;
                                        root.browse(false, false);
                                    }
                                }
                            }
                            MovieText { visible: (root.selected.subjectCount || 0) > 10; text: "+" + (root.selected.subjectCount - 10) + " more"; color: MovieStyle.muted }
                        }
                        MovieText {
                            Layout.fillWidth: true; color: MovieStyle.muted; wrapMode: Text.Wrap
                            visible: (root.selected.languages || []).length > 0
                            text: "Languages: " + (root.selected.languages || []).map(root.languageLabel).join(", ")
                        }
                    }
                }
                TorrentSearch {
                    showStatus: false
                    id: torrentFind; objectName: "booksFind"
                    service: localService; host: root.host; showLoading: false
                    visible: root.active && root.tab === "torrent"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    title: Object.assign({}, root.selected, {kind:"book",year:root.selected.firstPublishYear || "",author:(root.selected.authors || [])[0] ? root.selected.authors[0].name : ""})
                    extraSearchEnabled: root.providerNames.length > 0
                    extraResults: root.findOffers; extraSearching: root.findOffersLoading
                    extraError: root.findOffersError; extraInfo: root.findOffersInfo
                    onExtraSearchRequested: query => root.searchProviders(query)
                    onExtraResultRequested: offer => root.downloadOffer(offer)
                    onContextReset: root.resetFindOffers()
                    onImported: {
                        service.request("local_files", {title:Object.assign({}, root.selected, {kind:"book"})}, (result, failure) => { if (!failure) root.localFiles = result; });
                        if (root.localMode) root.browse(false, false);
                    }
                }
                ColumnLayout {
                    id: editionPane; visible: root.tab === "editions"
                    Layout.fillWidth: true; Layout.fillHeight: true; spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        MovieText { Layout.fillWidth: true; text: root.selected.editionCount ? root.selected.editionCount + " editions" : "Editions"; font.bold: true }
                    }
                    MovieText { visible: !!root.editionsError; Layout.fillWidth: true; text: root.editionsError; color: MovieStyle.danger; wrapMode: Text.Wrap }
                    ListView {
                        id: editionList; objectName: "editionList"
                        Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 6
                        model: root.tab === "editions" ? root.editions : []
                        WheelScroll { view: editionList }
                        ScrollBar.vertical: MovieScrollBar {}
                        delegate: Item {
                            id: editionRow
                            required property var modelData
                            width: editionList.width; height: Math.max(76, editionContent.implicitHeight + 12)
                            Accessible.name: [modelData.title, modelData.year, (modelData.languages || []).map(root.languageLabel).join(", "), (modelData.publishers || []).join(", "), (modelData.isbn || []).join(", ")].filter(Boolean).join(". ")
                            RowLayout {
                                anchors.fill: parent; spacing: 10
                                Rectangle { Layout.preferredWidth: 44; Layout.preferredHeight: 62; color: MovieStyle.surface; radius: 3
                                    CrossfadeImage { cacheService: bookArt; anchors.fill: parent; anchors.margins: 2; source: editionRow.modelData.cover || ""; fillMode: Image.PreserveAspectFit; imageWidth: 100 }
                                }
                                ColumnLayout {
                                    id: editionContent; Layout.fillWidth: true; spacing: 3
                                    MovieText { Layout.fillWidth: true; text: editionRow.modelData.title; font.bold: true; wrapMode: Text.Wrap; maximumLineCount: 2 }
                                    MovieText { Layout.fillWidth: true; color: MovieStyle.muted; wrapMode: Text.Wrap
                                        text: [editionRow.modelData.year || editionRow.modelData.publishDate, (editionRow.modelData.languages || []).map(root.languageLabel).join(" / "), (editionRow.modelData.publishers || []).join(", "), editionRow.modelData.format, editionRow.modelData.pages ? editionRow.modelData.pages + " pages" : ""].filter(Boolean).join("   ·   ")
                                    }
                                    MovieText { Layout.fillWidth: true; color: MovieStyle.muted; text: "ISBN " + (editionRow.modelData.isbn || []).join(" · "); visible: (editionRow.modelData.isbn || []).length > 0; wrapMode: Text.Wrap }
                                }
                            }
                            Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: MovieStyle.border }
                        }
                        footer: ColumnLayout {
                            width: editionList.width; spacing: 6
                            MovieText { visible: !root.editionsLoading && !root.editionsError && !root.editions.length; text: "No edition records are available for this work."; color: MovieStyle.muted }
                            MovieButton { visible: !!root.editionsNext; enabled: !root.editionsLoading; text: root.editionsLoading ? "Loading editions…" : "Load more editions"; onClicked: root.loadEditions(true) }
                        }
                    }
                }
            }
            ColumnLayout {
                id: authorPane
                x: root.gridMode ? parent.width * 0.55 : 16
                y: 0
                width: root.gridMode ? parent.width * 0.45 : Math.min(parent.width * 0.7, 1000)
                height: root.gridMode ? parent.height : parent.height - Math.min(300, parent.height * 0.34) - 16
                visible: root.tab === "author"
                spacing: 10
                RowLayout {
                    Layout.fillWidth: true; Layout.preferredHeight: 112; spacing: 12
                    MovieIconButton { iconName: "chevron-left"; text: "Back to book"; Accessible.name: "Back to selected book"; onClicked: root.tab = "overview" }
                    Rectangle {
                        Layout.preferredWidth: 78; Layout.preferredHeight: 96; color: MovieStyle.surface; radius: 5
                        CrossfadeImage { cacheService: bookArt; anchors.fill: parent; anchors.margins: 2; source: root.authorDetails.image || ""; fillMode: Image.PreserveAspectFit; imageWidth: 180 }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        MovieText { Layout.fillWidth: true; text: root.authorDetails.name || root.author.name || "Unknown author"; font.family: MovieStyle.fontFamily; font.pixelSize: root.fontSize(23); font.bold: true; wrapMode: Text.Wrap; maximumLineCount: 2 }
                        MovieText { Layout.fillWidth: true; text: [root.authorDetails.birthDate, root.authorDetails.deathDate ? "– " + root.authorDetails.deathDate : ""].filter(Boolean).join("   ·   "); color: MovieStyle.muted; wrapMode: Text.Wrap }
                    }
                }
                MovieText { visible: !!root.authorError; Layout.fillWidth: true; text: root.authorError; color: MovieStyle.danger; wrapMode: Text.Wrap; maximumLineCount: 2 }
                ScrollArea {
                    Layout.fillWidth: true; Layout.preferredHeight: Math.min(112, authorPane.height * 0.27); clip: true
                    contentWidth: availableWidth
                    MovieText { width: parent.width; text: root.authorDetails.biography || (root.authorLoading ? "Loading biography…" : "No biography available."); wrapMode: Text.Wrap }
                }
                MovieText { text: "Other works"; font.bold: true }
                GridView {
                    id: authorGrid; objectName: "authorWorksGrid"
                    Keys.onReturnPressed: if (currentItem) root.selectBook(currentItem.book)
                    Keys.onEnterPressed: if (currentItem) root.selectBook(currentItem.book)
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true; model: authorCatalogue
                    cellWidth: width / Math.max(2, Math.floor(width / 145)); cellHeight: cellWidth * 1.5 + 48
                    activeFocusOnTab: true; keyNavigationEnabled: true; keyNavigationWraps: false
                    delegate: BookCard {
                    cacheService: bookArt
                        required property string payload
                        readonly property var modelData: JSON.parse(payload)
                        required property int index
                        highlighted: authorGrid.activeFocus && authorGrid.currentIndex === index
                        width: authorGrid.cellWidth - 8; height: authorGrid.cellHeight - 8; book: modelData
                        onClicked: root.selectBook(modelData)
                    }
                    WheelScroll { view: authorGrid; wheelStep: Math.max(360, authorGrid.cellHeight * 1.25) }
                    ScrollBar.vertical: MovieScrollBar {}
                    footer: MovieButton { visible: !!root.authorNext; enabled: !root.authorLoading; text: root.authorLoading ? "Loading works…" : "Load more works"; onClicked: root.loadAuthorWorks(true) }
                }
            }
            ScrollArea {
                objectName: "booksScan"
                anchors.fill: parent
                visible: root.active && root.tab === "scan"
                contentWidth: availableWidth
                LocalScan {
                    showStatus: false
                    width: parent.width
                    id: scanPanel
                    kind: "book"; service: localService; showLoading: false
                    onImported: root.refreshLocalLibrary()
                }
            }
            ListView {
                id: rail; objectName: "catalogueRail"; visible: !root.gridMode && root.tab !== "author" && root.tab !== "scan"
                anchors.bottom: parent.bottom; width: parent.width; height: Math.min(300, parent.height * 0.34)
                orientation: ListView.Horizontal; spacing: 12; clip: true; model: catalogue
                activeFocusOnTab: true; keyNavigationEnabled: true; keyNavigationWraps: false
                delegate: BookCard {
                    cacheService: bookArt
                    required property string payload
                    readonly property var modelData: JSON.parse(payload)
                    required property int index
                    width: Math.min(170, (rail.height - 60) / 1.45); height: rail.height; book: modelData
                    highlighted: root.sameBook(root.selected, modelData)
                    onClicked: { rail.forceActiveFocus(); rail.currentIndex = index; root.selectBook(modelData); }
                }
                onCurrentItemChanged: if (!root.updatingCatalogue && activeFocus && currentItem && !root.sameBook(currentItem.book, root.selected)) root.selectBook(currentItem.book)
                Keys.onReturnPressed: if (currentItem) root.selectBook(currentItem.book)
                Keys.onEnterPressed: if (currentItem) root.selectBook(currentItem.book)
                onContentXChanged: pagination.restart()
                WheelScroll { view: rail; orientation: Qt.Horizontal; verticalToHorizontal: true; wheelStep: 360 }
                ScrollBar.horizontal: MovieScrollBar {}
            }
            MovieText {
                anchors.centerIn: parent; width: Math.min(420, parent.width - 56); horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
                visible: !root.books.length && root.tab !== "scan"
                text: root.loading || root.error ? "" : root.localMode ? "No local books yet." : root.favorites ? "No saved favorites yet." : "No books match this search."
                color: MovieStyle.muted
            }
        }
    }
}
