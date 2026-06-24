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
}

struct RootView: View {
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
    @State private var pinnedHistoryIDs: Set<UUID> = []
    @State private var hiddenHistoryIDs: Set<UUID> = []
    @State private var renamedHistoryTitles: [UUID: String] = [:]

    init() {
        let demoScreen = DocumentationDemoScreen.current
        let session = AppSession(service: BackendRecommendationService(), documentationDemo: demoScreen?.rawValue)

        _session = State(initialValue: session)
        _path = State(initialValue: demoScreen?.initialPath ?? [])
    }

    var body: some View {
        GeometryReader { geometry in
            let drawerWidth = min(340, geometry.size.width * 0.86)

            ZStack(alignment: .leading) {
                chatStack
                    .scaleEffect(showsDrawer ? 0.985 : 1)
                    .offset(x: showsDrawer ? drawerWidth * 0.12 : 0)
                    .allowsHitTesting(!showsDrawer)
                    .animation(.spring(response: 0.34, dampingFraction: 0.9), value: showsDrawer)

                if showsDrawer {
                    Color.black.opacity(0.18)
                        .ignoresSafeArea()
                        .transition(.opacity)
                        .onTapGesture {
                            closeDrawer()
                        }
                }

                ChatDrawer(
                    history: session.history,
                    pinnedHistoryIDs: $pinnedHistoryIDs,
                    hiddenHistoryIDs: $hiddenHistoryIDs,
                    renamedHistoryTitles: $renamedHistoryTitles,
                    onClose: closeDrawer,
                    onNewConversation: startNewConversationFromDrawer,
                    onSelectHistory: openHistoryItem,
                    onOpenAnswerDeck: { openDrawerRoute(.answerDeck) },
                    onOpenMyHelp: { openDrawerRoute(.myHelp) },
                    onOpenMyAnswers: { openDrawerRoute(.myAnswers) },
                    onOpenFavorites: { openDrawerRoute(.favorites) },
                    onOpenRewards: { openDrawerRoute(.rewards) },
                    onOpenMessages: { openDrawerRoute(.messages) },
                    onOpenProfile: { openDrawerRoute(.profile) },
                    onLogin: {
                        closeDrawer()
                        showsEmailLogin = true
                    },
                    unreadLightCount: unreadLightCount
                )
                .frame(width: drawerWidth)
                .offset(x: showsDrawer ? 0 : -drawerWidth - 24)
                .animation(.spring(response: 0.34, dampingFraction: 0.9), value: showsDrawer)
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
            startAnswerPolling()
            refreshMessageBadge()
        }
        .onDisappear {
            answerPollTask?.cancel()
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
                    MyHelpScreen(session: session, onSelectHistory: openHistoryItem)
                case .myAnswers:
                    MyAnswersScreen(session: session, onOpenAnswerDeck: {
                        path.removeAll()
                        path.append(.answerDeck)
                    })
                case .favorites:
                    FavoritesScreen(session: session, onSelectHistory: openHistoryItem)
                case .rewards:
                    RewardsScreen(authRevision: authRevision)
                case .messages:
                    MessagesScreen(onMarkRead: markLightEventsRead)
                case .profile:
                    ProfileScreen(
                        session: session,
                        authRevision: authRevision,
                        onManageAccount: {
                            showsEmailLogin = true
                        },
                        onHistorySelect: openHistoryItem,
                        onOpenAnswerDeck: {
                            path.removeAll()
                            path.append(.answerDeck)
                        }
                    )
                }
            }
        }
    }

    private func openDrawer() {
        withAnimation(.spring(response: 0.34, dampingFraction: 0.9)) {
            showsDrawer = true
        }
    }

    private func closeDrawer() {
        withAnimation(.spring(response: 0.3, dampingFraction: 0.92)) {
            showsDrawer = false
        }
    }

    private func startNewConversationFromDrawer() {
        session.startNewConversation()
        path.removeAll()
        chatRevision += 1
        closeDrawer()
    }

    private func openDrawerRoute(_ route: AppRoute) {
        closeDrawer()
        path.removeAll()
        path.append(route)
    }

    private func openHistoryItem(_ item: QuestionHistory) {
        Task { @MainActor in
            closeDrawer()
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

    private func drawerGesture(edgeWidth: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 18)
            .onEnded { value in
                if showsDrawer, value.translation.width < -70 {
                    closeDrawer()
                    return
                }

                if !showsDrawer,
                   value.startLocation.x <= edgeWidth,
                   value.translation.width > 70 {
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
    private func loadMessageBadge() async {
        let snapshot = await ProfileAPIService().fetchSnapshot()
        let ids = Set(snapshot.lightEvents.map(\.id))
        latestLightEventIDs = ids
        unreadLightCount = ids.subtracting(seenLightEventIDs()).count
    }

    private func markLightEventsRead(_ events: [UserLightEvent]) {
        var seen = seenLightEventIDs()
        seen.formUnion(latestLightEventIDs)
        seen.formUnion(events.map(\.id))
        seenLightEventIDsRaw = seen.sorted().joined(separator: ",")
        unreadLightCount = 0
    }

    private func seenLightEventIDs() -> Set<String> {
        Set(
            seenLightEventIDsRaw
                .split(separator: ",")
                .map { String($0) }
                .filter { !$0.isEmpty }
        )
    }
}

private struct ChatDrawer: View {
    let history: [QuestionHistory]
    @Binding var pinnedHistoryIDs: Set<UUID>
    @Binding var hiddenHistoryIDs: Set<UUID>
    @Binding var renamedHistoryTitles: [UUID: String]
    let onClose: () -> Void
    let onNewConversation: () -> Void
    let onSelectHistory: (QuestionHistory) -> Void
    let onOpenAnswerDeck: () -> Void
    let onOpenMyHelp: () -> Void
    let onOpenMyAnswers: () -> Void
    let onOpenFavorites: () -> Void
    let onOpenRewards: () -> Void
    let onOpenMessages: () -> Void
    let onOpenProfile: () -> Void
    let onLogin: () -> Void
    let unreadLightCount: Int

    @State private var searchText = ""
    @State private var renamingItem: QuestionHistory?
    @State private var renameText = ""

    private var visibleHistory: [QuestionHistory] {
        history.filter { item in
            !hiddenHistoryIDs.contains(item.id)
            && (searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || effectiveTitle(for: item).localizedCaseInsensitiveContains(searchText)
                || item.statusLabel.localizedCaseInsensitiveContains(searchText))
        }
    }

    private var pinnedHistory: [QuestionHistory] {
        visibleHistory.filter { pinnedHistoryIDs.contains($0.id) }
    }

    private var recentHistory: [QuestionHistory] {
        visibleHistory.filter { !pinnedHistoryIDs.contains($0.id) }
    }

    var body: some View {
        VStack(spacing: 0) {
            drawerHeader

            ScrollView {
                VStack(alignment: .leading, spacing: AppTheme.Spacing.lg) {
                    drawerSearch
                    newConversationButton
                    featureEntrances

                    if !pinnedHistory.isEmpty {
                        historySection(title: "置顶", items: pinnedHistory)
                    }

                    if !recentHistory.isEmpty {
                        let today = Array(recentHistory.prefix(3))
                        let week = Array(recentHistory.dropFirst(3).prefix(7))
                        let earlier = Array(recentHistory.dropFirst(10))

                        if !today.isEmpty {
                            historySection(title: "今天", items: today)
                        }
                        if !week.isEmpty {
                            historySection(title: "7 天内", items: week)
                        }
                        if !earlier.isEmpty {
                            historySection(title: "更早", items: earlier)
                        }
                    } else if !searchText.isEmpty {
                        DrawerEmptyState(text: "没有找到相关会话")
                    } else if pinnedHistory.isEmpty {
                        DrawerEmptyState(text: "还没有历史会话")
                    }
                }
                .padding(.horizontal, AppTheme.Spacing.lg)
                .padding(.bottom, AppTheme.Spacing.xxl)
            }
            .scrollIndicators(.hidden)

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
                    } else {
                        renamedHistoryTitles[item.id] = trimmed
                    }
                }
                renamingItem = nil
                renameText = ""
            }
        } message: {
            Text("只会修改本机显示名称。")
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
        }
        .buttonStyle(.plain)
    }

    private var featureEntrances: some View {
        VStack(spacing: AppTheme.Spacing.xs) {
            DrawerActionRow(icon: "bubble.left.and.bubble.right", title: "来一句", subtitle: "帮别人少纠结一次", action: onOpenAnswerDeck)
            DrawerActionRow(icon: "questionmark.bubble", title: "我的求一个", subtitle: "草稿、收集中和已完成", action: onOpenMyHelp)
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
        Button(action: onLogin) {
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
        .overlay(alignment: .top) {
            Rectangle()
                .fill(AppTheme.border)
                .frame(height: 1)
        }
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
                        onPinToggle: { togglePinned(item.id) },
                        onDelete: { hiddenHistoryIDs.insert(item.id) }
                    )
                }
            }
        }
    }

    private func effectiveTitle(for item: QuestionHistory) -> String {
        renamedHistoryTitles[item.id] ?? item.query
    }

    private func togglePinned(_ id: UUID) {
        if pinnedHistoryIDs.contains(id) {
            pinnedHistoryIDs.remove(id)
        } else {
            pinnedHistoryIDs.insert(id)
        }
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
                        .foregroundStyle(.white)
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
        .contextMenu {
            Button(isPinned ? "取消置顶" : "置顶", systemImage: isPinned ? "pin.slash" : "pin", action: onPinToggle)
            Button("重命名", systemImage: "pencil", action: onRename)
            Button("删除", systemImage: "trash", role: .destructive, action: onDelete)
        }
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
