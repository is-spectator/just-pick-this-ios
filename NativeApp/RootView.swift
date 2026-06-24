import SwiftUI

enum AppRoute: Hashable {
    case resultDatong
    case askKorea
}

enum AppTab: Hashable {
    case pipi
    case answer
    case profile
}

struct RootView: View {
    @State private var path: [AppRoute]
    @State private var selectedTab: AppTab
    @State private var session: AppSession
    @State private var answerPollTask: Task<Void, Never>?
    @State private var showsEmailLogin = false
    @State private var authRevision = 0

    init() {
        let demoScreen = DocumentationDemoScreen.current
        let session = AppSession(service: BackendRecommendationService(), documentationDemo: demoScreen?.rawValue)

        _session = State(initialValue: session)
        _path = State(initialValue: demoScreen?.initialPath ?? [])
        _selectedTab = State(initialValue: demoScreen == .answer ? .answer : .pipi)
    }

    var body: some View {
        TabView(selection: $selectedTab) {
            pipiTab
                .tag(AppTab.pipi)
                .tabItem {
                    Label("皮皮", systemImage: "sparkles")
                }

            answerTab
                .tag(AppTab.answer)
                .tabItem {
                    Label("来一句", systemImage: "bubble.left.and.bubble.right")
                }

            profileTab
                .tag(AppTab.profile)
                .tabItem {
                    Label("我的", systemImage: "person.crop.circle")
                }
        }
        .tint(AppTheme.text)
        .toolbarBackground(.visible, for: .tabBar)
        .toolbarBackground(.ultraThinMaterial, for: .tabBar)
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
        }
        .onDisappear {
            answerPollTask?.cancel()
        }
    }

    private var pipiTab: some View {
        NavigationStack(path: $path) {
            InputScreen(
                session: session,
                onDecision: { decision in
                    selectedTab = .pipi
                    switch decision {
                    case .none:
                        break
                    case .top1:
                        path.append(.resultDatong)
                    case .ask:
                        path.append(.askKorea)
                    }
                },
                onAnswerEntry: nil,
                onAccountEntry: {
                    selectedTab = .profile
                },
                onHistorySelect: { item in
                    openHistoryItem(item)
                }
            )
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
                }
            }
        }
    }

    private var answerTab: some View {
        NavigationStack {
            AnswerScreen(session: session, showsTopBar: false)
                .navigationBarHidden(true)
        }
    }

    private var profileTab: some View {
        NavigationStack {
            ProfileScreen(
                session: session,
                authRevision: authRevision,
                onManageAccount: {
                    showsEmailLogin = true
                },
                onHistorySelect: { item in
                    openHistoryItem(item)
                },
                onOpenAnswerDeck: {
                    selectedTab = .answer
                }
            )
        }
    }

    private func openHistoryItem(_ item: QuestionHistory) {
        Task { @MainActor in
            let destination = await session.restoreHistoryItem(item)
            selectedTab = .pipi
            path.removeAll()
            switch destination {
            case .result:
                path.append(.resultDatong)
            case .ask:
                path.append(.askKorea)
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
                    selectedTab = .pipi
                    path.removeAll()
                    path.append(.askKorea)
                }
            }
        }
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
            []
        }
    }
}

#Preview {
    RootView()
}
