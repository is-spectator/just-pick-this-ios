import SwiftUI

struct InputScreen: View {
    let session: AppSession
    let onDecision: (RecommendationDecision) -> Void
    let onAnswerEntry: () -> Void
    let onHistorySelect: (QuestionHistory) -> Void

    @State private var draft = ""
    @State private var isHistoryExpanded = false
    @State private var submitTask: Task<Void, Never>?

    var body: some View {
        AppChrome(showsBack: false, backAction: nil) {
            ZStack(alignment: .leading) {
                VStack {
                    HStack {
                        Spacer()
                        Button(action: onAnswerEntry) {
                            HStack(spacing: 6) {
                                Image(systemName: "quote.bubble")
                                Text("来一句")
                            }
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(AppTheme.text)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                            .background(AppTheme.card)
                            .clipShape(Capsule())
                            .overlay(
                                Capsule()
                                    .stroke(AppTheme.border, lineWidth: 1)
                            )
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("来一句")
                    }
                    .padding(.top, 4)

                    Spacer()

                    VStack(spacing: 12) {
                        Text("你在哪?")
                            .font(.system(size: 26, weight: .medium))
                            .foregroundStyle(AppTheme.text)

                        if session.isSubmitting {
                            HStack(spacing: 8) {
                                ProgressView()
                                    .tint(AppTheme.textMuted)

                                Text("正在想一个...")
                                    .font(.system(size: 13))
                                    .foregroundStyle(AppTheme.textMuted)
                            }
                            .transition(.opacity.combined(with: .move(edge: .top)))
                        }

                        if let notice = session.serviceNotice {
                            ServiceNoticePill(notice: notice)
                                .padding(.top, 4)
                                .transition(.opacity.combined(with: .move(edge: .top)))
                        }
                    }
                    .padding(.bottom, 110)

                    Spacer()
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(.horizontal, 36)

                if !session.history.isEmpty {
                    HistoryRail(
                        history: Array(session.history.prefix(3)),
                        isExpanded: $isHistoryExpanded,
                        onSelect: onHistorySelect
                    )
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                        .padding(.bottom, 14)
                }
            }
        } footer: {
            BottomComposer(
                text: $draft,
                placeholder: MockData.query,
                isSending: session.isSubmitting
            ) {
                submit()
            }
        }
        .onDisappear {
            submitTask?.cancel()
        }
        .animation(.easeOut(duration: 0.18), value: session.isSubmitting)
    }

    private func submit() {
        let query = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty, !session.isSubmitting else { return }

        submitTask?.cancel()
        submitTask = Task { @MainActor in
            let decision = await session.submit(query: query)
            guard !Task.isCancelled else { return }
            draft = ""
            onDecision(decision)
        }
    }
}

struct ResultScreen: View {
    let session: AppSession
    let onAskHuman: () -> Void
    let onDecision: (RecommendationDecision) -> Void
    let onAccepted: () -> Void
    let onBackHome: () -> Void

    @State private var draft = ""
    @State private var isFollowingUp = false
    @State private var isAccepting = false

    var body: some View {
        AppChrome(showsBack: true, backAction: onBackHome) {
            ScrollView {
                VStack(spacing: 0) {
                    QueryBubble(text: session.currentQuery.isEmpty ? MockData.query : session.currentQuery)

                    if let notice = session.serviceNotice {
                        ServiceNoticePill(notice: notice)
                            .padding(.bottom, 12)
                    }

                    DecisionCard(
                        pick: session.topPick,
                        isFollowingUp: isFollowingUp,
                        isAccepting: isAccepting,
                        onFollowup: followUp,
                        onAskHuman: onAskHuman,
                        onReject: onAskHuman,
                        onAccept: accept
                    )
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 18)
            }
            .scrollIndicators(.hidden)
        } footer: {
            BottomComposer(text: $draft, placeholder: "继续问一句", isSending: isFollowingUp) {
                submitDraftFollowup()
            }
        }
    }

    private func submitDraftFollowup() {
        let question = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty else { return }
        draft = ""
        followUp(question)
    }

    private func followUp(_ question: String) {
        guard !isFollowingUp, !isAccepting else { return }
        let baseQuery = session.currentQuery.isEmpty ? MockData.query : session.currentQuery
        let followupQuery = "\(baseQuery)；\(question)"
        isFollowingUp = true
        Task { @MainActor in
            let decision = await session.submit(query: followupQuery)
            guard !Task.isCancelled else { return }
            isFollowingUp = false
            onDecision(decision)
        }
    }

    private func accept() {
        guard !isAccepting else { return }
        isAccepting = true
        Task { @MainActor in
            await session.acceptCurrentTopPick()
            isAccepting = false
            onAccepted()
        }
    }
}

struct AskScreen: View {
    let session: AppSession
    let onHome: () -> Void

    @State private var draft = ""
    @State private var isPublishing = false
    @State private var toastMessage = "发出去了,等别人来一句。"
    @State private var showsToast = false
    @State private var publishTask: Task<Void, Never>?
    @State private var pollTask: Task<Void, Never>?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        AppChrome(showsBack: true, backAction: goBack) {
            ZStack {
                ScrollView {
                    VStack(spacing: 0) {
                        PageIntro(
                            title: session.helpRequest.answers.isEmpty ? "求一个" : "有人来一句了",
                            subtitle: session.helpRequest.answers.isEmpty
                                ? "这题我不硬选。\n我帮你发出去,等懂的人来一句。"
                                : "先看这一句,够用就别再刷了。"
                        )
                        if let notice = session.serviceNotice {
                            ServiceNoticePill(notice: notice)
                                .padding(.bottom, 16)
                        }
                        RequestCard(request: session.helpRequest)
                        if !session.helpRequest.answers.isEmpty {
                            PrimaryButton(title: "采纳这句") {
                                acceptAnswer()
                            }
                            .padding(.top, 20)
                        }
                        if session.helpRequest.status == .draft {
                            PrimaryButton(title: isPublishing ? "发出去中" : "发出去") {
                                publish()
                            }
                            .disabled(isPublishing)
                            .opacity(isPublishing ? 0.52 : 1)
                            .padding(.top, 20)
                        } else if session.helpRequest.answers.isEmpty {
                            PrimaryButton(title: "回首页") {
                                onHome()
                            }
                            .padding(.top, 20)
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.bottom, 18)
                }
                .scrollIndicators(.hidden)

                ToastView(message: toastMessage, isVisible: showsToast)
            }
        } footer: {
            if session.helpRequest.status == .draft {
                BottomComposer(text: $draft, placeholder: "补一句背景", isSending: isPublishing) {
                    session.addHelpContext(draft)
                    draft = ""
                }
            } else {
                Color.clear
                    .frame(height: 20)
            }
        }
        .onAppear {
            startPolling()
        }
        .onDisappear {
            publishTask?.cancel()
            pollTask?.cancel()
        }
    }

    private func publish() {
        guard session.helpRequest.status == .draft, !isPublishing else { return }
        isPublishing = true
        publishTask?.cancel()
        publishTask = Task { @MainActor in
            await session.publishCurrentRequest()
            isPublishing = false
            toastMessage = "发出去了,等别人来一句。"
            showsToast = true
            try? await Task.sleep(for: .milliseconds(650))
            guard !Task.isCancelled else { return }
            showsToast = false
            onHome()
        }
    }

    private func goBack() {
        guard !isPublishing else { return }
        if session.helpRequest.status == .draft {
            dismiss()
        } else {
            onHome()
        }
    }

    private func startPolling() {
        pollTask?.cancel()
        pollTask = Task { @MainActor in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(2))
                guard !Task.isCancelled else { return }
                let hasNewAnswer = await session.refreshCurrentHelpRequest()
                if hasNewAnswer {
                    toastMessage = "有人来一句了。"
                    showsToast = true
                    try? await Task.sleep(for: .milliseconds(1_400))
                    showsToast = false
                }
            }
        }
    }

    private func acceptAnswer() {
        Task { @MainActor in
            await session.acceptCurrentHelpAnswer()
            onHome()
        }
    }
}

struct AnswerScreen: View {
    let session: AppSession

    @State private var draft = ""
    @State private var showsToast = false
    @State private var toastTask: Task<Void, Never>?

    var body: some View {
        AppChrome(showsBack: true, backAction: nil) {
            ZStack {
                ScrollView {
                    VStack(spacing: 0) {
                        PageIntro(title: "来一句", subtitle: "帮 TA 少纠结一次。")
                        if let request = session.answerRequest {
                            AnswerRequestSquareCard(request: request, reward: "+10")
                        } else {
                            EmptyAnswerQueueCard()
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.bottom, 18)
                }
                .scrollIndicators(.hidden)

                ToastView(message: "收到了,+10 等她采纳。", isVisible: showsToast)
            }
        } footer: {
            BottomComposer(text: $draft, placeholder: "别去明洞当背景板,去圣水。") {
                sendAnswer()
            }
        }
        .task {
            await session.loadAnswerQueue()
        }
        .onDisappear {
            toastTask?.cancel()
        }
    }

    private func sendAnswer() {
        let answer = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !answer.isEmpty, session.answerRequest != nil else { return }
        draft = ""
        toastTask?.cancel()
        showsToast = true
        toastTask = Task { @MainActor in
            await session.addAnswer(answer)
            try? await Task.sleep(for: .milliseconds(1_600))
            guard !Task.isCancelled else { return }
            showsToast = false
        }
    }
}

struct ServiceNoticePill: View {
    let notice: ServiceNotice

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(AppTheme.orangeText)
                .padding(.top, 1)

            VStack(alignment: .leading, spacing: 2) {
                Text(notice.title)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(AppTheme.orangeText)

                Text(notice.detail)
                    .font(.system(size: 12))
                    .lineSpacing(2)
                    .foregroundStyle(AppTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.orangeBackground)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(notice.title), \(notice.detail)")
    }
}

struct HistoryPanel: View {
    let history: [QuestionHistory]
    let onSelect: (QuestionHistory) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("最近问过")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(AppTheme.textMuted)

            ForEach(history) { item in
                Button {
                    onSelect(item)
                } label: {
                    HStack(spacing: 10) {
                        Text(item.query)
                            .font(.system(size: 13))
                            .foregroundStyle(AppTheme.textSecondary)
                            .lineLimit(1)

                        Spacer()

                        Text(item.statusLabel)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(AppTheme.textMuted)

                        Image(systemName: "chevron.right")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(AppTheme.textMuted)
                    }
                    .frame(minHeight: 36)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("打开最近问过 \(item.query)")
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(AppTheme.border, lineWidth: 1)
        )
    }
}

struct HistoryRail: View {
    let history: [QuestionHistory]
    @Binding var isExpanded: Bool
    let onSelect: (QuestionHistory) -> Void

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            Button {
                withAnimation(.easeOut(duration: 0.2)) {
                    isExpanded.toggle()
                }
            } label: {
                VStack(spacing: 7) {
                    Image(systemName: isExpanded ? "chevron.left" : "clock.arrow.circlepath")
                        .font(.system(size: 14, weight: .semibold))

                    Text("最近")
                        .font(.system(size: 12, weight: .medium))
                }
                .foregroundStyle(AppTheme.text)
                .frame(width: 42, height: 92)
                .background(AppTheme.card)
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .stroke(AppTheme.border, lineWidth: 1)
                )
                .shadow(color: .black.opacity(0.06), radius: 16, x: 0, y: 8)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(isExpanded ? "收起最近问过" : "展开最近问过")

            if isExpanded {
                HistoryPanel(history: history, onSelect: onSelect)
                    .frame(width: 292)
                    .transition(.move(edge: .leading).combined(with: .opacity))
            }
        }
        .padding(.leading, -4)
    }
}

struct EmptyAnswerQueueCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("暂时没人求一个")
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(AppTheme.text)

            Text("等有人发出求一个,这里会出现可以回答的卡片。")
                .font(.system(size: 13))
                .lineSpacing(4)
                .foregroundStyle(AppTheme.textSecondary)
        }
        .padding(22)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .stroke(AppTheme.border, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.06), radius: 24, x: 0, y: 10)
    }
}

#Preview("Input") {
    InputScreen(
        session: AppSession(service: MockCloudRecommendationService()),
        onDecision: { _ in },
        onAnswerEntry: {},
        onHistorySelect: { _ in }
    )
}

#Preview("Result") {
    ResultScreen(session: AppSession(service: MockCloudRecommendationService()), onAskHuman: {}, onDecision: { _ in }, onAccepted: {}, onBackHome: {})
}

#Preview("Ask") {
    AskScreen(session: AppSession(service: MockCloudRecommendationService()), onHome: {})
}

#Preview("Answer") {
    AnswerScreen(session: AppSession(service: MockCloudRecommendationService()))
}
