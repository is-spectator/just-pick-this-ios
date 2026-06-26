import SwiftUI

enum AppRoute: Hashable {
    case resultDatong
    case askKorea
    case answerDeck
    case myHelp
    case myAnswers
    case favorites
    case rewards
    case messages
    case profile
    case helpDetail(QuestionHistory)
}

struct RootView: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var path: [AppRoute]
    @State private var session: AppSession
    @State private var answerPollTask: Task<Void, Never>?
    @AppStorage("seen_light_event_ids") private var seenLightEventIDsRaw = ""
    @State private var showsDrawer = false
    @State private var showsEmailLogin = false
    @State private var authRevision = 0
    @State private var chatRevision = 0
    @State private var unreadLightCount = 0
    @State private var latestLightEventIDs: Set<String> = []
    @State private var isDrawerRefreshing = false
    @State private var pinnedHistoryIDs: Set<UUID> = []
    @State private var hiddenHistoryIDs: Set<UUID> = []
    @State private var renamedHistoryTitles: [UUID: String] = [:]
    @AppStorage("pinned_history_ids") private var pinnedHistoryIDsRaw = ""
    @AppStorage("hidden_history_ids") private var hiddenHistoryIDsRaw = ""
    @AppStorage("renamed_history_titles") private var renamedHistoryTitlesRaw = ""
    @GestureState private var drawerDragTranslation: CGFloat = 0

    private let drawerAnimation = Animation.spring(response: 0.34, dampingFraction: 0.88)
    private var activeDrawerAnimation: Animation? {
        reduceMotion ? nil : drawerAnimation
    }

    init() {
        let demoScreen = DocumentationDemoScreen.current
        let session = AppSession(service: BackendRecommendationService(), documentationDemo: demoScreen?.rawValue)

        _session = State(initialValue: session)
        _path = State(initialValue: demoScreen?.initialPath ?? [])
    }

    var body: some View {
        GeometryReader { geometry in
            let drawerWidth = min(340, geometry.size.width * 0.86)
            let drawerProgress = drawerProgress(for: drawerWidth)

            ZStack(alignment: .leading) {
                chatStack
                    .scaleEffect(reduceMotion ? 1 : 1 - 0.015 * drawerProgress)
                    .offset(x: reduceMotion ? 0 : drawerWidth * 0.12 * drawerProgress)
                    .allowsHitTesting(!showsDrawer)
                    .animation(activeDrawerAnimation, value: showsDrawer)

                Color.black.opacity(0.18 * drawerProgress)
                    .ignoresSafeArea()
                    .allowsHitTesting(showsDrawer)
                    .onTapGesture {
                        closeDrawer()
                    }

                ChatDrawer(
                    history: session.history,
                    favoriteChoices: session.favoriteChoices,
                    hiddenFavoriteChoiceIds: session.hiddenFavoriteChoiceIds,
                    pinnedHistoryIDs: $pinnedHistoryIDs,
                    hiddenHistoryIDs: $hiddenHistoryIDs,
                    renamedHistoryTitles: $renamedHistoryTitles,
                    onClose: { closeDrawer() },
                    onNewConversation: startNewConversationFromDrawer,
                    onSelectHistory: openHistoryItem,
                    onDeleteHistory: deleteHistoryItemFromDrawer,
                    onRestoreHistory: restoreHistoryItemFromDrawer,
                    onOpenAnswerDeck: { openDrawerRoute(.answerDeck) },
                    onOpenMyHelp: { openDrawerRoute(.myHelp) },
                    onOpenMyAnswers: { openDrawerRoute(.myAnswers) },
                    onOpenFavorites: { openDrawerRoute(.favorites) },
                    onOpenRewards: { openDrawerRoute(.rewards) },
                    onOpenMessages: { openDrawerRoute(.messages) },
                    onOpenProfile: { openDrawerRoute(.profile) },
                    onLogin: {
                        AppHaptics.selection()
                        closeDrawer(haptic: false)
                        showsEmailLogin = true
                    },
                    unreadLightCount: unreadLightCount,
                    isRefreshing: isDrawerRefreshing,
                    onRefresh: refreshDrawer
                )
                .frame(width: drawerWidth)
                .offset(x: drawerOffset(for: drawerWidth, progress: drawerProgress))
                .animation(activeDrawerAnimation, value: showsDrawer)
            }
            .contentShape(Rectangle())
            .simultaneousGesture(drawerGesture(edgeWidth: 28))
        }
        .sheet(isPresented: $showsEmailLogin) {
            EmailLoginView(authService: AuthAPIService()) {
                showsEmailLogin = false
                authRevision += 1
            }
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
        .onAppear {
            restoreDrawerHistoryPreferences()
            startAnswerPolling()
            refreshMessageBadge()
        }
        .onDisappear {
            answerPollTask?.cancel()
        }
        .onChange(of: pinnedHistoryIDs) { _, value in
            pinnedHistoryIDsRaw = encodeUUIDSet(value)
        }
        .onChange(of: hiddenHistoryIDs) { _, value in
            hiddenHistoryIDsRaw = encodeUUIDSet(value)
        }
        .onChange(of: renamedHistoryTitles) { _, value in
            renamedHistoryTitlesRaw = encodeRenamedHistoryTitles(value)
        }
    }

    private var chatStack: some View {
        NavigationStack(path: $path) {
            InputScreen(
                session: session,
                showsMessageBadge: unreadLightCount > 0,
                onDecision: { decision in
                    switch decision {
                    case .none:
                        break
                    case .top1:
                        path.append(.resultDatong)
                    case .ask:
                        path.append(.askKorea)
                    }
                },
                onMenu: openDrawer,
                onHistorySelect: openHistoryItem
            )
            .id(chatRevision)
            .navigationDestination(for: AppRoute.self) { route in
                switch route {
                case .resultDatong:
                    ResultScreen(
                        session: session,
                        onAskHuman: {
                            session.makeHelpRequestFromCurrentTopPick()
                            path.append(.askKorea)
                        },
                        onDecision: { decision in
                            if case .ask = decision {
                                path.append(.askKorea)
                            }
                        },
                        onAccepted: { path.removeAll() },
                        onBackHome: { path.removeAll() }
                    )
                case .askKorea:
                    AskScreen(
                        session: session,
                        onHome: { path.removeAll() }
                    )
                case .answerDeck:
                    AnswerScreen(session: session)
                case .myHelp:
                    MyHelpScreen(session: session, onSelectHelpDetail: openHelpDetail)
                case .myAnswers:
                    MyAnswersScreen(session: session, onOpenAnswerDeck: {
                        path.removeAll()
                        path.append(.answerDeck)
                    }, onOpenAnswerRequest: { request in
                        session.selectAnswerRequest(request)
                        path.removeAll()
                        path.append(.answerDeck)
                    }, onSelectHelpDetail: openHelpDetail)
                case .favorites:
                    FavoritesScreen(session: session, onSelectHistory: openHistoryItem)
                case .rewards:
                    RewardsScreen(
                        session: session,
                        authRevision: authRevision,
                        onSelectHelpDetail: openHelpDetail
                    )
                case .messages:
                    MessagesScreen(
                        onEventsLoaded: noteLightEventsLoaded,
                        onMarkRead: markLightEventsRead,
                        onOpenEvent: openLightEvent
                    )
                case .profile:
                    ProfileScreen(
                        session: session,
                        authRevision: authRevision,
                        onManageAccount: {
                            showsEmailLogin = true
                        },
                        onAuthChanged: {
                            authRevision += 1
                            chatRevision += 1
                            restoreDrawerHistoryPreferences()
                            refreshMessageBadge()
                        },
                        onHistorySelect: openHistoryItem,
                        onOpenAnswerDeck: {
                            path.removeAll()
                            path.append(.answerDeck)
                        }
                    )
                case .helpDetail(let item):
                    HelpResultDetailScreen(session: session, historyItem: item)
                }
            }
        }
    }

    private func openDrawer() {
        guard !showsDrawer else { return }
        AppHaptics.selection()
        withAnimation(activeDrawerAnimation) {
            showsDrawer = true
        }
    }

    private func closeDrawer(haptic: Bool = true) {
        guard showsDrawer else { return }
        if haptic {
            AppHaptics.selection()
        }
        withAnimation(reduceMotion ? nil : .spring(response: 0.3, dampingFraction: 0.9)) {
            showsDrawer = false
        }
    }

    private func startNewConversationFromDrawer() {
        session.startNewConversation()
        path.removeAll()
        chatRevision += 1
        AppHaptics.success()
        closeDrawer(haptic: false)
    }

    private func openDrawerRoute(_ route: AppRoute) {
        AppHaptics.selection()
        closeDrawer(haptic: false)
        path.removeAll()
        path.append(route)
    }

    private func openHistoryItem(_ item: QuestionHistory) {
        AppHaptics.selection()
        Task { @MainActor in
            closeDrawer(haptic: false)
            let destination = await session.restoreHistoryItem(item)
            path.removeAll()
            switch destination {
            case .result:
                path.append(.resultDatong)
            case .ask:
                path.append(.askKorea)
            }
        }
    }

    private func deleteHistoryItemFromDrawer(_ item: QuestionHistory) {
        session.deleteHistoryItem(id: item.id)
        pinnedHistoryIDs.remove(item.id)
        renamedHistoryTitles[item.id] = nil
    }

    private func restoreHistoryItemFromDrawer(_ item: QuestionHistory) {
        session.restoreDeletedHistoryItem(item)
    }

    private func openHelpDetail(_ item: QuestionHistory) {
        AppHaptics.selection()
        closeDrawer(haptic: false)
        path.append(.helpDetail(item))
    }

    private func openLightEvent(_ event: UserLightEvent) {
        if let helpCardId = event.helpCardId {
            let item = session.history.first { $0.helpRequestId == helpCardId } ?? QuestionHistory(
                id: helpCardId,
                query: event.title,
                status: "answer_received",
                helpRequestId: helpCardId,
                topPick: nil,
                createdAt: event.createdAt
            )
            path.append(.helpDetail(item))
            return
        }

        if let cardId = event.cardId,
           let item = session.history.first(where: { $0.topPick?.cardId == cardId }) {
            Task { @MainActor in
                let destination = await session.restoreHistoryItem(item)
                switch destination {
                case .result:
                    path.append(.resultDatong)
                case .ask:
                    path.append(.askKorea)
                }
            }
            return
        }

        if event.kind?.contains("reward") == true {
            path.append(.rewards)
        } else {
            path.append(.myHelp)
        }
    }

    private func drawerProgress(for drawerWidth: CGFloat) -> CGFloat {
        let baseProgress: CGFloat = showsDrawer ? 1 : 0
        let dragProgress = drawerDragTranslation / max(drawerWidth, 1)
        return min(max(baseProgress + dragProgress, 0), 1)
    }

    private func drawerOffset(for drawerWidth: CGFloat, progress: CGFloat) -> CGFloat {
        let hiddenOffset = -drawerWidth - 24
        return hiddenOffset * (1 - progress)
    }

    private func drawerGesture(edgeWidth: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 12, coordinateSpace: .global)
            .updating($drawerDragTranslation) { value, state, _ in
                let horizontal = value.translation.width
                let vertical = value.translation.height
                guard abs(horizontal) > abs(vertical) else { return }

                if showsDrawer {
                    state = min(0, horizontal)
                    return
                }

                if value.startLocation.x <= edgeWidth {
                    state = max(0, horizontal)
                }
            }
            .onEnded { value in
                let horizontal = value.translation.width
                let predictedHorizontal = value.predictedEndTranslation.width
                let vertical = value.translation.height
                guard abs(horizontal) > abs(vertical) else { return }

                if showsDrawer {
                    if min(horizontal, predictedHorizontal) < -96 {
                        closeDrawer()
                    } else {
                        openDrawer()
                    }
                    return
                }

                if !showsDrawer,
                   value.startLocation.x <= edgeWidth,
                   max(horizontal, predictedHorizontal) > 76 {
                    openDrawer()
                }
            }
    }

    private func startAnswerPolling() {
        answerPollTask?.cancel()
        answerPollTask = Task { @MainActor in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(3))
                guard !Task.isCancelled else { return }
                guard path.last != .askKorea else { continue }
                let hasNewAnswer = await session.refreshCurrentHelpRequest()
                if hasNewAnswer {
                    path.removeAll()
                    path.append(.askKorea)
                }
                await loadMessageBadge()
            }
        }
    }

    private func refreshMessageBadge() {
        Task { @MainActor in
            await loadMessageBadge()
        }
    }

    @MainActor
    private func refreshDrawer() async {
        guard !isDrawerRefreshing else { return }
        isDrawerRefreshing = true
        defer { isDrawerRefreshing = false }

        _ = await session.refreshCurrentHelpRequest()
        await session.loadAnswerQueue()
        await loadMessageBadge()
    }

    @MainActor
    private func loadMessageBadge() async {
        let snapshot = await ProfileAPIService().fetchSnapshot()
        let ids = Set(snapshot.lightEvents.map(\.id))
        latestLightEventIDs = ids
        unreadLightCount = ids.subtracting(seenLightEventIDs()).count
    }

    private func markLightEventsRead(_ events: [UserLightEvent]) {
        var seen = seenLightEventIDs()
        if latestLightEventIDs.isEmpty {
            latestLightEventIDs.formUnion(events.map(\.id))
        }
        seen.formUnion(events.map(\.id))
        seenLightEventIDsRaw = seen.sorted().joined(separator: ",")
        unreadLightCount = latestLightEventIDs.subtracting(seen).count
    }

    private func noteLightEventsLoaded(_ events: [UserLightEvent]) {
        let ids = Set(events.map(\.id))
        latestLightEventIDs = ids
        unreadLightCount = ids.subtracting(seenLightEventIDs()).count
    }

    private func seenLightEventIDs() -> Set<String> {
        Set(
            seenLightEventIDsRaw
                .split(separator: ",")
                .map { String($0) }
                .filter { !$0.isEmpty }
        )
    }

    private func restoreDrawerHistoryPreferences() {
        pinnedHistoryIDs = decodeUUIDSet(pinnedHistoryIDsRaw)
        hiddenHistoryIDs = decodeUUIDSet(hiddenHistoryIDsRaw)
        renamedHistoryTitles = decodeRenamedHistoryTitles(renamedHistoryTitlesRaw)
    }
}

private func encodeUUIDSet(_ value: Set<UUID>) -> String {
    value
        .map(\.uuidString)
        .sorted()
        .joined(separator: ",")
}

private func decodeUUIDSet(_ value: String) -> Set<UUID> {
    Set(
        value
            .split(separator: ",")
            .compactMap { UUID(uuidString: String($0)) }
    )
}

private func encodeRenamedHistoryTitles(_ value: [UUID: String]) -> String {
    let payload = value.reduce(into: [String: String]()) { partial, item in
        let trimmed = item.value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        partial[item.key.uuidString] = trimmed
    }
    guard let data = try? JSONEncoder().encode(payload),
          let encoded = String(data: data, encoding: .utf8) else {
        return "{}"
    }
    return encoded
}

private func decodeRenamedHistoryTitles(_ value: String) -> [UUID: String] {
    guard let data = value.data(using: .utf8),
          let payload = try? JSONDecoder().decode([String: String].self, from: data) else {
        return [:]
    }
    return payload.reduce(into: [UUID: String]()) { partial, item in
        guard let id = UUID(uuidString: item.key) else { return }
        let trimmed = item.value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        partial[id] = trimmed
    }
}

private struct ChatDrawer: View {
    let history: [QuestionHistory]
    let favoriteChoices: [QuestionHistory]
    let hiddenFavoriteChoiceIds: Set<UUID>
    @Binding var pinnedHistoryIDs: Set<UUID>
    @Binding var hiddenHistoryIDs: Set<UUID>
    @Binding var renamedHistoryTitles: [UUID: String]
    let onClose: () -> Void
    let onNewConversation: () -> Void
    let onSelectHistory: (QuestionHistory) -> Void
    let onDeleteHistory: (QuestionHistory) -> Void
    let onRestoreHistory: (QuestionHistory) -> Void
    let onOpenAnswerDeck: () -> Void
    let onOpenMyHelp: () -> Void
    let onOpenMyAnswers: () -> Void
    let onOpenFavorites: () -> Void
    let onOpenRewards: () -> Void
    let onOpenMessages: () -> Void
    let onOpenProfile: () -> Void
    let onLogin: () -> Void
    let unreadLightCount: Int
    let isRefreshing: Bool
    let onRefresh: () async -> Void

    @State private var searchText = ""
    @State private var renamingItem: QuestionHistory?
    @State private var renameText = ""
    @State private var deletingItem: QuestionHistory?
    @State private var deletedHistorySnapshot: DeletedHistorySnapshot?
    @State private var drawerNotice: String?
    @State private var drawerNoticeTask: Task<Void, Never>?

    private var searchQuery: String {
        searchText.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var isSearching: Bool {
        !searchQuery.isEmpty
    }

    private var baseVisibleHistory: [QuestionHistory] {
        history.filter { item in
            !hiddenHistoryIDs.contains(item.id)
        }
    }

    private var visibleHistory: [QuestionHistory] {
        baseVisibleHistory.filter(matchesSearch)
    }

    private var pinnedHistory: [QuestionHistory] {
        visibleHistory.filter { pinnedHistoryIDs.contains($0.id) }
    }

    private var recentHistory: [QuestionHistory] {
        visibleHistory.filter { !pinnedHistoryIDs.contains($0.id) }
    }

    private var matchingHistory: [QuestionHistory] {
        baseVisibleHistory.filter { item in
            !isHelpItem(item)
            && !isFavoriteCandidate(item)
            && matchesSearch(item)
        }
    }

    private var matchingHelp: [QuestionHistory] {
        baseVisibleHistory.filter { isHelpItem($0) && matchesSearch($0) }
    }

    private var searchableFavorites: [QuestionHistory] {
        let historyChoices = baseVisibleHistory.filter { isFavoriteCandidate($0) && !hiddenFavoriteChoiceIds.contains($0.id) }
        return favoriteChoices + historyChoices.filter { item in
            !favoriteChoices.contains(where: { $0.id == item.id })
        }
    }

    private var matchingFavorites: [QuestionHistory] {
        searchableFavorites.filter(matchesSearch)
    }

    private var hasSearchResults: Bool {
        !matchingHistory.isEmpty || !matchingHelp.isEmpty || !matchingFavorites.isEmpty
    }

    var body: some View {
        VStack(spacing: 0) {
            drawerHeader

            ScrollView {
                VStack(alignment: .leading, spacing: AppTheme.Spacing.lg) {
                    drawerSearch

                    if let drawerNotice {
                        if deletedHistorySnapshot == nil {
                            DrawerNoticePill(text: drawerNotice)
                        } else {
                            DrawerNoticePill(
                                text: drawerNotice,
                                actionTitle: "撤销",
                                action: undoDeletedHistory
                            )
                        }
                    }

                    if isSearching {
                        searchResults
                    } else {
                        newConversationButton
                        featureEntrances
                        defaultHistorySections
                    }
                }
                .padding(.horizontal, AppTheme.Spacing.lg)
                .padding(.bottom, AppTheme.Spacing.xxl)
            }
            .scrollIndicators(.hidden)
            .refreshable {
                await onRefresh()
            }

            accountEntry
        }
        .background(AppTheme.surface.ignoresSafeArea())
        .overlay(alignment: .trailing) {
            Rectangle()
                .fill(AppTheme.border)
                .frame(width: 1)
        }
        .alert("重命名会话", isPresented: renameAlertBinding) {
            TextField("会话名称", text: $renameText)
            Button("取消", role: .cancel) {
                renamingItem = nil
                renameText = ""
            }
            Button("保存") {
                if let item = renamingItem {
                    let trimmed = renameText.trimmingCharacters(in: .whitespacesAndNewlines)
                    if trimmed.isEmpty {
                        renamedHistoryTitles[item.id] = nil
                        showDrawerNotice("已恢复原会话名")
                    } else {
                        renamedHistoryTitles[item.id] = trimmed
                        showDrawerNotice("已重命名会话")
                    }
                    AppHaptics.success()
                }
                renamingItem = nil
                renameText = ""
            }
        } message: {
            Text("只会修改本机显示名称。")
        }
        .confirmationDialog("删除这条会话？", isPresented: deleteConfirmationBinding, titleVisibility: .visible) {
            Button("删除会话", role: .destructive) {
                if let deletingItem {
                    hideHistory(deletingItem)
                }
                deletingItem = nil
            }
            Button("取消", role: .cancel) {
                deletingItem = nil
            }
        } message: {
            if let deletingItem {
                Text("会从这台设备的抽屉历史里移除“\(effectiveTitle(for: deletingItem))”。")
            } else {
                Text("会从这台设备的抽屉历史里移除。")
            }
        }
        .onDisappear {
            drawerNoticeTask?.cancel()
        }
    }

    @ViewBuilder
    private var defaultHistorySections: some View {
        if isRefreshing && pinnedHistory.isEmpty && recentHistory.isEmpty {
            DrawerHistorySkeletonSection()
        } else if !pinnedHistory.isEmpty {
            historySection(title: "置顶", items: pinnedHistory)

            if !recentHistory.isEmpty {
                recentHistorySections
            }
        } else if !recentHistory.isEmpty {
            recentHistorySections
        } else {
            DrawerEmptyState(text: "还没有历史会话")
        }
    }

    @ViewBuilder
    private var recentHistorySections: some View {
        let today = recentHistory.filter { historyGroup(for: $0) == .today }
        let week = recentHistory.filter { historyGroup(for: $0) == .week }
        let earlier = recentHistory.filter { historyGroup(for: $0) == .earlier }

        if !today.isEmpty {
            historySection(title: "今天", items: today)
        }
        if !week.isEmpty {
            historySection(title: "7 天内", items: week)
        }
        if !earlier.isEmpty {
            historySection(title: "更早", items: earlier)
        }
    }

    @ViewBuilder
    private var searchResults: some View {
        if hasSearchResults {
            if !matchingHistory.isEmpty {
                searchResultSection(title: "历史会话", items: matchingHistory, icon: "message")
            }
            if !matchingHelp.isEmpty {
                searchResultSection(title: "求一个", items: matchingHelp, icon: "questionmark.bubble")
            }
            if !matchingFavorites.isEmpty {
                searchResultSection(title: "收藏", items: matchingFavorites, icon: "bookmark")
            }
        } else {
            DrawerEmptyState(text: "没有找到相关历史、求一个或收藏")
        }
    }

    private var renameAlertBinding: Binding<Bool> {
        Binding(
            get: { renamingItem != nil },
            set: { isPresented in
                if !isPresented {
                    renamingItem = nil
                    renameText = ""
                }
            }
        )
    }

    private var deleteConfirmationBinding: Binding<Bool> {
        Binding(
            get: { deletingItem != nil },
            set: { isPresented in
                if !isPresented {
                    deletingItem = nil
                }
            }
        )
    }

    private var drawerHeader: some View {
        HStack(spacing: AppTheme.Spacing.sm) {
            Text("皮皮")
                .font(AppTheme.Typography.title)
                .foregroundStyle(AppTheme.text)

            Spacer()

            Button(action: onClose) {
                Image(systemName: "xmark")
                    .font(AppTheme.Icon.row)
                    .foregroundStyle(AppTheme.textSecondary)
                    .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("关闭菜单")
        }
        .padding(.horizontal, AppTheme.Spacing.lg)
        .padding(.top, AppTheme.Spacing.xl)
        .padding(.bottom, AppTheme.Spacing.sm)
    }

    private var drawerSearch: some View {
        HStack(spacing: AppTheme.Spacing.xs) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(AppTheme.textMuted)

            TextField("搜索历史、求一个和收藏", text: $searchText)
                .font(AppTheme.Typography.body)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()

            if !searchText.isEmpty {
                Button {
                    searchText = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(AppTheme.textMuted)
                        .frame(width: 32, height: 32)
                        .contentShape(Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("清空搜索")
            }
        }
        .padding(.horizontal, AppTheme.Spacing.md)
        .frame(height: 48)
        .background(AppTheme.bubble)
        .clipShape(RoundedRectangle(cornerRadius: AppTheme.Radius.chip, style: .continuous))
    }

    private var newConversationButton: some View {
        Button(action: onNewConversation) {
            HStack(spacing: AppTheme.Spacing.sm) {
                Image(systemName: "plus.message")
                    .font(AppTheme.Icon.row)
                Text("新对话")
                    .font(.system(size: 16, weight: .semibold))
                Spacer()
            }
            .foregroundStyle(AppTheme.text)
            .frame(minHeight: 48)
            .padding(.horizontal, AppTheme.Spacing.md)
            .background(AppTheme.text.opacity(0.06))
            .clipShape(RoundedRectangle(cornerRadius: AppTheme.Radius.chip, style: .continuous))
            .contentShape(RoundedRectangle(cornerRadius: AppTheme.Radius.chip, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("新对话")
        .accessibilityHint("清空当前聊天并开始新的选择")
    }

    private var featureEntrances: some View {
        VStack(spacing: AppTheme.Spacing.xs) {
            DrawerActionRow(icon: "bubble.left.and.bubble.right", title: "来一句", subtitle: "帮别人少纠结一次", action: onOpenAnswerDeck)
            DrawerActionRow(icon: "questionmark.bubble", title: "我的求一个", subtitle: "草稿、收集中和已关闭", action: onOpenMyHelp)
            DrawerActionRow(icon: "quote.bubble", title: "我的回答", subtitle: "待采纳、已采纳和未采用", action: onOpenMyAnswers)
            DrawerActionRow(icon: "bookmark", title: "收藏", subtitle: "保存过的选择", action: onOpenFavorites)
            DrawerActionRow(icon: "gift", title: "奖励", subtitle: "积分和采纳明细", action: onOpenRewards)
            DrawerActionRow(
                icon: "bell",
                title: "消息中心",
                subtitle: unreadLightCount > 0 ? "\(unreadLightCount) 条新进展" : "回答、结果和奖励提醒",
                badgeCount: unreadLightCount,
                action: onOpenMessages
            )
        }
    }

    private var accountEntry: some View {
        Button(action: isSignedIn ? onOpenProfile : onLogin) {
            HStack(spacing: AppTheme.Spacing.sm) {
                Image(systemName: AuthTokenStore.email == nil ? "person.crop.circle" : "person.crop.circle.fill")
                    .font(.system(size: 28, weight: .medium))
                    .foregroundStyle(AppTheme.text)
                    .frame(width: 44, height: 44)

                VStack(alignment: .leading, spacing: 3) {
                    Text(AuthTokenStore.displayName ?? (AuthTokenStore.email == nil ? "登录" : "已登录"))
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(AppTheme.text)
                    Text(AuthTokenStore.email ?? "同步历史、奖励和账号")
                        .font(AppTheme.Typography.caption)
                        .foregroundStyle(AppTheme.textSecondary)
                        .lineLimit(1)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(AppTheme.textMuted)
            }
            .padding(.horizontal, AppTheme.Spacing.lg)
            .frame(height: 72)
            .background(AppTheme.surface)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(isSignedIn ? "账号与设置" : "登录")
        .accessibilityValue(AuthTokenStore.email ?? "未登录")
        .accessibilityHint(isSignedIn ? "打开我的页面，管理账号、隐私和数据" : "登录后同步历史、奖励和账号")
        .overlay(alignment: .top) {
            Rectangle()
                .fill(AppTheme.border)
                .frame(height: 1)
        }
    }

    private var isSignedIn: Bool {
        AuthTokenStore.email != nil
    }

    @ViewBuilder
    private func historySection(title: String, items: [QuestionHistory]) -> some View {
        VStack(alignment: .leading, spacing: AppTheme.Spacing.xs) {
            Text(title)
                .font(AppTheme.Typography.caption.weight(.semibold))
                .foregroundStyle(AppTheme.textMuted)
                .padding(.horizontal, AppTheme.Spacing.xs)

            VStack(spacing: 2) {
                ForEach(items) { item in
                    DrawerHistoryRow(
                        title: effectiveTitle(for: item),
                        subtitle: item.statusLabel,
                        isPinned: pinnedHistoryIDs.contains(item.id),
                        onOpen: { onSelectHistory(item) },
                        onRename: {
                            renamingItem = item
                            renameText = effectiveTitle(for: item)
                        },
                        onPinToggle: { togglePinned(item) },
                        onDelete: { requestDeleteHistory(item) }
                    )
                }
            }
        }
    }

    @ViewBuilder
    private func searchResultSection(title: String, items: [QuestionHistory], icon: String) -> some View {
        VStack(alignment: .leading, spacing: AppTheme.Spacing.xs) {
            Text(title)
                .font(AppTheme.Typography.caption.weight(.semibold))
                .foregroundStyle(AppTheme.textMuted)
                .padding(.horizontal, AppTheme.Spacing.xs)

            VStack(spacing: 2) {
                ForEach(items) { item in
                    DrawerSearchResultRow(
                        icon: icon,
                        title: searchTitle(for: item),
                        subtitle: searchSubtitle(for: item),
                        isPinned: pinnedHistoryIDs.contains(item.id),
                        onOpen: { onSelectHistory(item) },
                        onRename: {
                            renamingItem = item
                            renameText = effectiveTitle(for: item)
                        },
                        onPinToggle: { togglePinned(item) },
                        onDelete: { requestDeleteHistory(item) }
                    )
                }
            }
        }
    }

    private func effectiveTitle(for item: QuestionHistory) -> String {
        renamedHistoryTitles[item.id] ?? item.query
    }

    private func searchTitle(for item: QuestionHistory) -> String {
        item.topPick?.title ?? effectiveTitle(for: item)
    }

    private func searchSubtitle(for item: QuestionHistory) -> String {
        if let reason = item.topPick?.reason, !reason.isEmpty {
            return reason
        }
        return item.statusLabel
    }

    private func matchesSearch(_ item: QuestionHistory) -> Bool {
        guard isSearching else { return true }
        let haystack = [
            effectiveTitle(for: item),
            item.query,
            item.statusLabel,
            item.topPick?.title,
            item.topPick?.subtitle,
            item.topPick?.reason
        ]
        return haystack.compactMap { $0 }.contains { value in
            value.localizedCaseInsensitiveContains(searchQuery)
        }
    }

    private func isHelpItem(_ item: QuestionHistory) -> Bool {
        item.helpRequestId != nil
        || item.status == "waiting_for_human"
        || item.status == "answer_received"
        || item.status == "closed"
    }

    private func isFavoriteCandidate(_ item: QuestionHistory) -> Bool {
        item.topPick != nil || item.status == "completed" || item.status == "top1" || item.status == "saved"
    }

    private func historyGroup(for item: QuestionHistory) -> DrawerHistoryDateGroup {
        guard let date = historyDate(for: item) else { return .today }
        let calendar = Calendar.current
        if calendar.isDateInToday(date) {
            return .today
        }

        let startOfToday = calendar.startOfDay(for: Date())
        let startOfDate = calendar.startOfDay(for: date)
        guard let days = calendar.dateComponents([.day], from: startOfDate, to: startOfToday).day else {
            return .earlier
        }
        return (1...7).contains(days) ? .week : .earlier
    }

    private func historyDate(for item: QuestionHistory) -> Date? {
        guard let createdAt = item.createdAt, !createdAt.isEmpty else { return nil }
        let fractionalFormatter = ISO8601DateFormatter()
        fractionalFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return fractionalFormatter.date(from: createdAt) ?? formatter.date(from: createdAt)
    }

    private func togglePinned(_ item: QuestionHistory) {
        AppHaptics.selection()
        if pinnedHistoryIDs.contains(item.id) {
            pinnedHistoryIDs.remove(item.id)
            showDrawerNotice("已取消置顶")
        } else {
            pinnedHistoryIDs.insert(item.id)
            showDrawerNotice("已置顶会话")
        }
    }

    private func requestDeleteHistory(_ item: QuestionHistory) {
        AppHaptics.warning()
        deletingItem = item
    }

    private func hideHistory(_ item: QuestionHistory) {
        deletedHistorySnapshot = DeletedHistorySnapshot(
            item: item,
            wasPinned: pinnedHistoryIDs.contains(item.id),
            renamedTitle: renamedHistoryTitles[item.id]
        )
        hiddenHistoryIDs.insert(item.id)
        pinnedHistoryIDs.remove(item.id)
        renamedHistoryTitles[item.id] = nil
        onDeleteHistory(item)
        AppHaptics.success()
        showDrawerNotice("已删除会话")
    }

    private func undoDeletedHistory() {
        guard let snapshot = deletedHistorySnapshot else { return }
        drawerNoticeTask?.cancel()
        hiddenHistoryIDs.remove(snapshot.item.id)
        if snapshot.wasPinned {
            pinnedHistoryIDs.insert(snapshot.item.id)
        }
        if let renamedTitle = snapshot.renamedTitle {
            renamedHistoryTitles[snapshot.item.id] = renamedTitle
        }
        onRestoreHistory(snapshot.item)
        deletedHistorySnapshot = nil
        AppHaptics.success()
        showDrawerNotice("已恢复会话")
    }

    private func showDrawerNotice(_ text: String) {
        drawerNoticeTask?.cancel()
        drawerNotice = text
        drawerNoticeTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(1_500))
            guard !Task.isCancelled else { return }
            drawerNotice = nil
            if text == "已删除会话" {
                deletedHistorySnapshot = nil
            }
        }
    }
}

private struct DeletedHistorySnapshot {
    let item: QuestionHistory
    let wasPinned: Bool
    let renamedTitle: String?
}

private enum DrawerHistoryDateGroup {
    case today
    case week
    case earlier
}

private struct DrawerNoticePill: View {
    let text: String
    var actionTitle: String?
    var action: (() -> Void)?

    var body: some View {
        HStack(spacing: AppTheme.Spacing.xs) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(AppTheme.green)

            Text(text)
                .font(AppTheme.Typography.caption.weight(.semibold))
                .foregroundStyle(AppTheme.textSecondary)

            Spacer(minLength: 0)

            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .font(AppTheme.Typography.caption.weight(.semibold))
                    .foregroundStyle(AppTheme.text)
                    .buttonStyle(.plain)
                    .frame(minWidth: 44, minHeight: 32)
                    .accessibilityHint("恢复刚才删除的会话")
            }
        }
        .padding(.horizontal, AppTheme.Spacing.md)
        .frame(minHeight: 40)
        .background(AppTheme.green.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: AppTheme.Radius.chip, style: .continuous))
        .accessibilityElement(children: action == nil ? .combine : .contain)
        .accessibilityLabel(text)
    }
}

private struct DrawerActionRow: View {
    let icon: String
    let title: String
    let subtitle: String
    var badgeCount: Int = 0
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: AppTheme.Spacing.sm) {
                Image(systemName: icon)
                    .font(AppTheme.Icon.row)
                    .foregroundStyle(AppTheme.text)
                    .frame(width: 32, height: 32)

                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(AppTheme.text)
                    Text(subtitle)
                        .font(AppTheme.Typography.caption)
                        .foregroundStyle(AppTheme.textSecondary)
                        .lineLimit(1)
                }

                Spacer()

                if badgeCount > 0 {
                    Text(badgeCount > 99 ? "99+" : "\(badgeCount)")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(AppTheme.onBadge)
                        .padding(.horizontal, 6)
                        .frame(minWidth: 22, minHeight: 20)
                        .background(AppTheme.red)
                        .clipShape(Capsule())
                }
            }
            .padding(.horizontal, AppTheme.Spacing.sm)
            .frame(minHeight: 54)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(accessibilityLabel)
        .accessibilityHint(subtitle)
    }

    private var accessibilityLabel: String {
        guard badgeCount > 0 else { return title }
        let countText = badgeCount > 99 ? "99 条以上" : "\(badgeCount) 条"
        return "\(title)，\(countText)新消息"
    }
}

private struct DrawerHistoryRow: View {
    let title: String
    let subtitle: String
    let isPinned: Bool
    let onOpen: () -> Void
    let onRename: () -> Void
    let onPinToggle: () -> Void
    let onDelete: () -> Void

    var body: some View {
        Button(action: onOpen) {
            HStack(spacing: AppTheme.Spacing.sm) {
                Image(systemName: isPinned ? "pin.fill" : "message")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(isPinned ? AppTheme.text : AppTheme.textMuted)
                    .frame(width: 28, height: 28)

                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.system(size: 15, weight: .medium))
                        .foregroundStyle(AppTheme.text)
                        .lineLimit(1)
                    Text(subtitle)
                        .font(AppTheme.Typography.caption)
                        .foregroundStyle(AppTheme.textMuted)
                        .lineLimit(1)
                }

                Spacer()
            }
            .padding(.horizontal, AppTheme.Spacing.sm)
            .frame(height: 56)
            .background(AppTheme.surface)
            .clipShape(RoundedRectangle(cornerRadius: AppTheme.Radius.chip, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
        .accessibilityHint(isPinned ? "打开置顶会话，长按可以取消置顶、重命名或删除" : "打开历史会话，长按可以置顶、重命名或删除")
        .contextMenu {
            Button(isPinned ? "取消置顶" : "置顶", systemImage: isPinned ? "pin.slash" : "pin", action: onPinToggle)
            Button("重命名", systemImage: "pencil", action: onRename)
            Button("删除", systemImage: "trash", role: .destructive, action: onDelete)
        }
    }
}

private struct DrawerSearchResultRow: View {
    let icon: String
    let title: String
    let subtitle: String
    let isPinned: Bool
    let onOpen: () -> Void
    let onRename: () -> Void
    let onPinToggle: () -> Void
    let onDelete: () -> Void

    var body: some View {
        Button(action: onOpen) {
            HStack(spacing: AppTheme.Spacing.sm) {
                Image(systemName: icon)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(AppTheme.textMuted)
                    .frame(width: 28, height: 28)

                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.system(size: 15, weight: .medium))
                        .foregroundStyle(AppTheme.text)
                        .lineLimit(1)
                    Text(subtitle)
                        .font(AppTheme.Typography.caption)
                        .foregroundStyle(AppTheme.textMuted)
                        .lineLimit(1)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(AppTheme.textMuted)
            }
            .padding(.horizontal, AppTheme.Spacing.sm)
            .frame(height: 56)
            .background(AppTheme.surface)
            .clipShape(RoundedRectangle(cornerRadius: AppTheme.Radius.chip, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
        .accessibilityHint(isPinned ? "打开搜索结果，长按可以取消置顶、重命名或删除" : "打开搜索结果，长按可以置顶、重命名或删除")
        .contextMenu {
            Button(isPinned ? "取消置顶" : "置顶", systemImage: isPinned ? "pin.slash" : "pin", action: onPinToggle)
            Button("重命名", systemImage: "pencil", action: onRename)
            Button("删除", systemImage: "trash", role: .destructive, action: onDelete)
        }
    }
}

private struct DrawerHistorySkeletonSection: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isBreathing = false

    var body: some View {
        VStack(alignment: .leading, spacing: AppTheme.Spacing.xs) {
            Capsule()
                .fill(AppTheme.textMuted.opacity(isBreathing ? 0.2 : 0.1))
                .frame(width: 52, height: 10)
                .padding(.horizontal, AppTheme.Spacing.xs)

            VStack(spacing: 2) {
                DrawerHistorySkeletonRow(width: 156, isBreathing: isBreathing)
                DrawerHistorySkeletonRow(width: 206, isBreathing: isBreathing)
                DrawerHistorySkeletonRow(width: 132, isBreathing: isBreathing)
            }
        }
        .accessibilityHidden(true)
        .onAppear {
            guard !reduceMotion else { return }
            withAnimation(.easeInOut(duration: 0.95).repeatForever(autoreverses: true)) {
                isBreathing = true
            }
        }
    }
}

private struct DrawerHistorySkeletonRow: View {
    let width: CGFloat
    let isBreathing: Bool

    var body: some View {
        HStack(spacing: AppTheme.Spacing.sm) {
            Circle()
                .fill(AppTheme.textMuted.opacity(isBreathing ? 0.18 : 0.08))
                .frame(width: 28, height: 28)

            VStack(alignment: .leading, spacing: 7) {
                Capsule()
                    .fill(AppTheme.textMuted.opacity(isBreathing ? 0.2 : 0.1))
                    .frame(width: width, height: 12)

                Capsule()
                    .fill(AppTheme.textMuted.opacity(isBreathing ? 0.15 : 0.07))
                    .frame(width: max(width * 0.62, 86), height: 9)
            }

            Spacer()
        }
        .padding(.horizontal, AppTheme.Spacing.sm)
        .frame(height: 56)
        .background(AppTheme.surface)
        .clipShape(RoundedRectangle(cornerRadius: AppTheme.Radius.chip, style: .continuous))
    }
}

private struct DrawerEmptyState: View {
    let text: String

    var body: some View {
        Text(text)
            .font(AppTheme.Typography.caption)
            .foregroundStyle(AppTheme.textMuted)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(AppTheme.Spacing.md)
            .background(AppTheme.bubble)
            .clipShape(RoundedRectangle(cornerRadius: AppTheme.Radius.chip, style: .continuous))
    }
}

private enum DocumentationDemoScreen: String {
    case result
    case ask
    case answer

    static var current: DocumentationDemoScreen? {
        #if DEBUG
        let prefix = "--demo-screen="
        guard let argument = ProcessInfo.processInfo.arguments.first(where: { $0.hasPrefix(prefix) }) else {
            return nil
        }

        return DocumentationDemoScreen(rawValue: String(argument.dropFirst(prefix.count)))
        #else
        return nil
        #endif
    }

    var initialPath: [AppRoute] {
        switch self {
        case .result:
            [.resultDatong]
        case .ask:
            [.askKorea]
        case .answer:
            [.answerDeck]
        }
    }
}

#Preview {
    RootView()
}
