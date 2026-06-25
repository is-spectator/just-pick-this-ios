import SwiftUI
import UIKit

private enum ChatEntry: Identifiable {
    case intro(UUID)
    case user(UUID, String)
    case notice(UUID, ServiceNotice)
    case recommendation(UUID, TopPick)
    case help(UUID, HelpRequest)

    var id: UUID {
        switch self {
        case .intro(let id),
             .user(let id, _),
             .notice(let id, _),
             .recommendation(let id, _),
             .help(let id, _):
            id
        }
    }

    var helpRequestId: UUID? {
        if case .help(_, let request) = self {
            return request.id
        }
        return nil
    }
}

private struct CardSharePayload: Identifiable {
    let id = UUID()
    let text: String
}

private struct ActivityShareSheet: UIViewControllerRepresentable {
    let items: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}

private enum AppHaptics {
    @MainActor
    static func selection() {
        UISelectionFeedbackGenerator().selectionChanged()
    }

    @MainActor
    static func success() {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }

    @MainActor
    static func warning() {
        UINotificationFeedbackGenerator().notificationOccurred(.warning)
    }
}

struct InputScreen: View {
    let session: AppSession
    let showsMessageBadge: Bool
    let onDecision: (RecommendationDecision) -> Void
    let onMenu: () -> Void
    let onHistorySelect: (QuestionHistory) -> Void

    @State private var draft = ""
    @State private var entries: [ChatEntry] = [.intro(UUID())]
    @State private var submitTask: Task<Void, Never>?
    @State private var toastTask: Task<Void, Never>?
    @State private var isAcceptingPick = false
    @State private var isPublishingHelp = false
    @State private var showsNewConversationToast = false
    @State private var decisionLocation: DecisionLocationContext?
    @State private var showsLocationPicker = false
    @State private var manualLocationText = ""
    @State private var isLocating = false
    @State private var locationMessage: String?
    @State private var isComposerFocused = false
    @State private var lastFailedQuery: String?
    @State private var sharePayload: CardSharePayload?
    @AppStorage("recent_decision_location_labels") private var recentDecisionLocationLabelsRaw = ""

    private var recentDecisionLocationLabels: [String] {
        recentDecisionLocationLabelsRaw
            .split(separator: "\n")
            .map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    private var suggestedDecisionLocationLabels: [String] {
        mergeLocationLabels(
            recentDecisionLocationLabels + [
                "北京三里屯",
                "北京市朝阳区",
                "望京 SOHO",
                "南锣鼓巷",
                "上海互联网宝地",
                "大同古城"
            ]
        )
    }

    var body: some View {
        AppChrome(
            showsBack: false,
            backAction: nil,
            onHistory: {
                dismissKeyboard()
                onMenu()
            },
            onNewConversation: startNewConversation,
            showsHistoryBadge: showsMessageBadge
        ) {
            VStack(spacing: 0) {
                DecisionLocationBar(
                    location: decisionLocation,
                    isLocating: isLocating,
                    action: {
                        dismissKeyboard()
                        manualLocationText = decisionLocation?.label ?? ""
                        showsLocationPicker = true
                    }
                )

                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 18) {
                            ForEach(entries) { entry in
                                row(for: entry)
                                    .id(entry.id)
                            }

                            if session.isSubmitting {
                                AssistantThinkingRow()
                                    .id("thinking")
                            }
                        }
                        .padding(.horizontal, 18)
                        .padding(.top, 14)
                        .padding(.bottom, 20)
                        .contentShape(Rectangle())
                        .onTapGesture {
                            dismissKeyboard()
                        }
                    }
                    .scrollIndicators(.hidden)
                    .scrollDismissesKeyboard(.interactively)
                    .simultaneousGesture(
                        DragGesture(minimumDistance: 8)
                            .onChanged { _ in dismissKeyboard() }
                    )
                    .onChange(of: entries.count) { _, _ in
                        scrollToBottom(with: proxy)
                    }
                    .onChange(of: session.isSubmitting) { _, _ in
                        scrollToBottom(with: proxy)
                    }
                }
            }
        } footer: {
            BottomComposer(
                text: $draft,
                placeholder: MockData.queryPlaceholder,
                focused: $isComposerFocused,
                isSending: session.isSubmitting
            ) {
                submit()
            }
        }
        .onDisappear {
            submitTask?.cancel()
            toastTask?.cancel()
        }
        .sheet(isPresented: $showsLocationPicker) {
            LocationPickerSheet(
                manualText: $manualLocationText,
                currentLocation: decisionLocation,
                isLocating: isLocating,
                message: locationMessage,
                suggestedLocations: suggestedDecisionLocationLabels,
                onUseCurrent: useCurrentLocation,
                onSelectSuggestion: selectSuggestedLocation,
                onSaveManual: saveManualLocation,
                onClear: clearDecisionLocation
            )
            .presentationDetents([.medium])
            .presentationDragIndicator(.visible)
        }
        .sheet(item: $sharePayload) { payload in
            ActivityShareSheet(items: [payload.text])
        }
        .overlay(alignment: .top) {
            if showsNewConversationToast {
                Text("已开启新对话")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(AppTheme.onPrimaryAction)
                    .padding(.horizontal, 14)
                    .frame(height: 36)
                    .background(AppTheme.primaryAction)
                    .clipShape(Capsule())
                    .padding(.top, 8)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .animation(.easeOut(duration: 0.18), value: session.isSubmitting)
    }

    @ViewBuilder
    private func row(for entry: ChatEntry) -> some View {
        switch entry {
        case .intro:
            AssistantIntroRow()
        case .user(_, let text):
            UserChatBubble(text: text)
        case .notice(_, let notice):
            if notice.isRetryable {
                AssistantNoticeRow(
                    notice: notice,
                    actionTitle: "重试",
                    action: retryLastFailedQuery
                )
            } else {
                AssistantNoticeRow(notice: notice)
            }
        case .recommendation(_, let pick):
            AssistantRecommendationRow(
                pick: pick,
                isAccepting: isAcceptingPick,
                onAskHuman: makeHelpRequestFromPick,
                onAccept: acceptPick,
                onFavorite: favoritePick,
                onChange: changePick,
                onReportIssue: reportPickIssue,
                onShare: sharePick
            )
        case .help(_, let request):
            AssistantHelpRow(
                request: request,
                isPublishing: isPublishingHelp,
                onPublish: { publish(request) }
            )
        }
    }

    private func submit() {
        let query = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty, !session.isSubmitting else { return }

        dismissKeyboard()
        submit(query)
    }

    private func submit(_ query: String) {
        draft = ""
        lastFailedQuery = nil
        entries.append(.user(UUID(), query))
        submitTask?.cancel()
        submitTask = Task { @MainActor in
            let decision = await session.submit(query: query, locationContext: decisionLocation)
            guard !Task.isCancelled else { return }
            appendAssistantResponse(for: decision, originalQuery: query)
        }
    }

    private func appendAssistantResponse(for decision: RecommendationDecision, originalQuery: String) {
        switch decision {
        case .none:
            if let notice = session.serviceNotice {
                if notice.isRetryable {
                    lastFailedQuery = originalQuery
                    draft = originalQuery
                }
                entries.append(.notice(UUID(), notice))
            }
        case .top1(let pick):
            lastFailedQuery = nil
            entries.append(.recommendation(UUID(), pick))
        case .ask(let request):
            lastFailedQuery = nil
            entries.append(.help(UUID(), request))
        }
    }

    private func retryLastFailedQuery() {
        let retryQuery = draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? lastFailedQuery?.trimmingCharacters(in: .whitespacesAndNewlines)
            : draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let retryQuery, !retryQuery.isEmpty, !session.isSubmitting else { return }

        dismissKeyboard()
        submit(retryQuery)
    }

    private func makeHelpRequestFromPick() {
        dismissKeyboard()
        AppHaptics.selection()
        session.makeHelpRequestFromCurrentTopPick()
        entries.append(.help(UUID(), session.helpRequest))
    }

    private func favoritePick() {
        dismissKeyboard()
        AppHaptics.success()
        session.saveCurrentTopPickToFavorites()
        entries.append(.notice(UUID(), ServiceNotice(title: "已收藏", detail: "这张推荐已经放进 Drawer 里的收藏。")))
    }

    private func changePick() {
        dismissKeyboard()
        AppHaptics.selection()
        Task { @MainActor in
            _ = await session.sendCurrentTopPickFeedback(action: .change, reason: "不合适，想换一个")
            entries.append(.notice(UUID(), ServiceNotice(title: "收到", detail: "我记下了：这张不合适。你可以补一句想换的方向。")))
        }
    }

    private func reportPickIssue() {
        dismissKeyboard()
        AppHaptics.warning()
        Task { @MainActor in
            _ = await session.sendCurrentTopPickFeedback(action: .reject, reason: "信息有误")
            entries.append(.notice(UUID(), ServiceNotice(title: "收到", detail: "这张卡已标记为信息有误，我会避开这类错误。")))
        }
    }

    private func sharePick() {
        dismissKeyboard()
        AppHaptics.selection()
        sharePayload = CardSharePayload(text: shareText(for: session.topPick))
    }

    private func shareText(for pick: TopPick) -> String {
        let reason = pick.reason.trimmingCharacters(in: .whitespacesAndNewlines)
        let subtitle = pick.subtitle.trimmingCharacters(in: .whitespacesAndNewlines)
        let detail = reason.isEmpty ? subtitle : reason
        guard !detail.isEmpty else { return "\(pick.title)\n来自皮皮" }
        return "\(pick.title)\n\(detail)\n来自皮皮"
    }

    private func acceptPick() {
        guard !isAcceptingPick else { return }
        dismissKeyboard()
        isAcceptingPick = true
        Task { @MainActor in
            await session.acceptCurrentTopPick()
            AppHaptics.success()
            isAcceptingPick = false
            entries.append(.notice(UUID(), ServiceNotice(title: "皮皮", detail: "就这个。")))
        }
    }

    private func publish(_ request: HelpRequest) {
        guard request.status == .draft, !isPublishingHelp else { return }
        dismissKeyboard()
        isPublishingHelp = true
        Task { @MainActor in
            await session.publishCurrentRequest()
            if let updated = session.currentHelpRequest {
                updateHelpEntry(updated)
            }
            AppHaptics.success()
            isPublishingHelp = false
            entries.append(.notice(UUID(), ServiceNotice(title: "皮皮", detail: "发出去了，等懂的人来一句。")))
        }
    }

    private func updateHelpEntry(_ request: HelpRequest) {
        guard let index = entries.firstIndex(where: { $0.helpRequestId == request.id }) else { return }
        entries[index] = .help(entries[index].id, request)
    }

    private func scrollToBottom(with proxy: ScrollViewProxy) {
        DispatchQueue.main.async {
            withAnimation(.easeOut(duration: 0.2)) {
                if session.isSubmitting {
                    proxy.scrollTo("thinking", anchor: .bottom)
                } else if let last = entries.last {
                    proxy.scrollTo(last.id, anchor: .bottom)
                }
            }
        }
    }

    private func startNewConversation() {
        submitTask?.cancel()
        dismissKeyboard()
        draft = ""
        session.startNewConversation()
        entries = [.intro(UUID())]
        showNewConversationToast()
    }

    private func showNewConversationToast() {
        toastTask?.cancel()
        withAnimation(.easeOut(duration: 0.18)) {
            showsNewConversationToast = true
        }
        toastTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 1_400_000_000)
            guard !Task.isCancelled else { return }
            withAnimation(.easeOut(duration: 0.18)) {
                showsNewConversationToast = false
            }
        }
    }

    private func openHistoryItem(_ item: QuestionHistory) {
        submitTask?.cancel()
        dismissKeyboard()
        draft = ""
        onHistorySelect(item)
    }

    private func useCurrentLocation() {
        guard !isLocating else { return }
        isLocating = true
        locationMessage = nil

        Task { @MainActor in
            if let location = await DeviceLocationProvider.shared.currentDecisionLocation() {
                decisionLocation = location
                manualLocationText = location.label
                rememberDecisionLocation(location.label)
                locationMessage = "已使用当前位置。"
                showsLocationPicker = false
            } else {
                locationMessage = "没拿到当前位置，可以手动输入地点。"
            }
            isLocating = false
        }
    }

    private func saveManualLocation() {
        guard let location = DecisionLocationContext.manual(manualLocationText) else {
            locationMessage = "先输入城市、区域或地标。"
            return
        }
        decisionLocation = location
        rememberDecisionLocation(location.label)
        locationMessage = "已使用\(location.label)。"
        showsLocationPicker = false
    }

    private func selectSuggestedLocation(_ label: String) {
        guard let location = DecisionLocationContext.manual(label) else { return }
        decisionLocation = location
        manualLocationText = location.label
        rememberDecisionLocation(location.label)
        locationMessage = "已使用\(location.label)。"
        showsLocationPicker = false
    }

    private func clearDecisionLocation() {
        decisionLocation = nil
        manualLocationText = ""
        locationMessage = nil
        showsLocationPicker = false
    }

    private func rememberDecisionLocation(_ label: String) {
        let trimmed = label.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        let labels = mergeLocationLabels([trimmed] + recentDecisionLocationLabels)
        recentDecisionLocationLabelsRaw = labels.prefix(6).joined(separator: "\n")
    }

    private func mergeLocationLabels(_ labels: [String]) -> [String] {
        var seen = Set<String>()
        var merged: [String] = []
        for label in labels {
            let trimmed = label.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { continue }
            let key = trimmed.localizedLowercase
            guard !seen.contains(key) else { continue }
            seen.insert(key)
            merged.append(trimmed)
        }
        return merged
    }

    private func dismissKeyboard() {
        isComposerFocused = false
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
    }
}

private struct DecisionLocationBar: View {
    let location: DecisionLocationContext?
    let isLocating: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: location == nil ? "location" : "location.fill")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(AppTheme.text)
                    .frame(width: 28, height: 28)
                    .background(AppTheme.bubble)
                    .clipShape(Circle())

                VStack(alignment: .leading, spacing: 2) {
                    Text(location?.displayLabel ?? "未设置决策地点")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(AppTheme.text)
                        .lineLimit(1)

                    Text(location?.detailLabel ?? "点这里使用当前定位或手动输入")
                        .font(AppTheme.Typography.caption)
                        .foregroundStyle(AppTheme.textSecondary)
                        .lineLimit(1)
                }

                Spacer(minLength: 8)

                if isLocating {
                    ProgressView()
                        .tint(AppTheme.text)
                        .scaleEffect(0.76)
                        .frame(width: 30, height: 30)
                } else {
                    Image(systemName: "chevron.down")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(AppTheme.textMuted)
                        .frame(width: 30, height: 30)
                }
            }
            .padding(.horizontal, 12)
            .frame(minHeight: 52)
            .background(AppTheme.card)
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(AppTheme.border, lineWidth: 1)
            )
            .padding(.horizontal, 18)
            .padding(.bottom, 8)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(location == nil ? "选择决策地点" : "当前决策地点：\(location?.displayLabel ?? "")")
        .accessibilityHint("打开地点选择，可使用当前定位、搜索或手动输入地点")
    }
}

private struct LocationPickerSheet: View {
    @Binding var manualText: String
    let currentLocation: DecisionLocationContext?
    let isLocating: Bool
    let message: String?
    let suggestedLocations: [String]
    let onUseCurrent: () -> Void
    let onSelectSuggestion: (String) -> Void
    let onSaveManual: () -> Void
    let onClear: () -> Void

    @Environment(\.dismiss) private var dismiss

    private var filteredSuggestions: [String] {
        let query = manualText.trimmingCharacters(in: .whitespacesAndNewlines)
        let candidates = suggestedLocations.filter { label in
            currentLocation?.label != label
        }
        guard !query.isEmpty else { return Array(candidates.prefix(6)) }
        return Array(
            candidates
                .filter { $0.localizedCaseInsensitiveContains(query) }
                .prefix(6)
        )
    }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("决策地点")
                        .font(.system(size: 24, weight: .semibold))
                        .foregroundStyle(AppTheme.text)

                    Text("皮皮会把这里当作附近推荐和步行距离的依据。")
                        .font(.system(size: 14))
                        .lineSpacing(4)
                        .foregroundStyle(AppTheme.textSecondary)
                }

                if let currentLocation {
                    HStack(spacing: 10) {
                        Image(systemName: currentLocation.source == "current" ? "location.fill" : "mappin.and.ellipse")
                            .font(.system(size: 15, weight: .semibold))
                            .foregroundStyle(AppTheme.green)
                            .frame(width: 34, height: 34)
                            .background(AppTheme.bubble)
                            .clipShape(Circle())

                        VStack(alignment: .leading, spacing: 3) {
                            Text(currentLocation.displayLabel)
                                .font(.system(size: 15, weight: .semibold))
                                .foregroundStyle(AppTheme.text)
                                .lineLimit(1)
                            Text(currentLocation.detailLabel)
                                .font(AppTheme.Typography.caption)
                                .foregroundStyle(AppTheme.textSecondary)
                        }
                    }
                    .productPanel()
                }

                Button(action: onUseCurrent) {
                    HStack(spacing: 12) {
                        Image(systemName: "location.circle.fill")
                            .font(.system(size: 21, weight: .semibold))
                            .foregroundStyle(AppTheme.onPrimaryAction)
                            .frame(width: 42, height: 42)
                            .background(AppTheme.primaryAction)
                            .clipShape(Circle())

                        VStack(alignment: .leading, spacing: 3) {
                            Text("使用当前定位")
                                .font(.system(size: 16, weight: .semibold))
                                .foregroundStyle(AppTheme.text)
                            Text("需要系统定位授权，只用于这次决策。")
                                .font(AppTheme.Typography.caption)
                                .foregroundStyle(AppTheme.textSecondary)
                        }

                        Spacer()

                        if isLocating {
                            ProgressView()
                                .tint(AppTheme.text)
                        }
                    }
                    .frame(minHeight: 58)
                }
                .buttonStyle(.plain)
                .disabled(isLocating)
                .accessibilityLabel(isLocating ? "正在获取当前定位" : "使用当前定位")
                .accessibilityHint("授权后把当前位置设为本次决策地点")

                VStack(alignment: .leading, spacing: 10) {
                    Text("搜索或输入地点")
                        .font(AppTheme.Typography.caption.weight(.semibold))
                        .foregroundStyle(AppTheme.textSecondary)

                    TextField("城市、区域或地标，例如 上海互联网宝地", text: $manualText)
                        .font(AppTheme.Typography.body)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .padding(.horizontal, 14)
                        .frame(height: 50)
                        .background(AppTheme.bubble)
                        .clipShape(RoundedRectangle(cornerRadius: AppTheme.Radius.chip, style: .continuous))

                    if !filteredSuggestions.isEmpty {
                        VStack(spacing: 2) {
                            ForEach(filteredSuggestions, id: \.self) { label in
                                LocationSuggestionRow(label: label) {
                                    onSelectSuggestion(label)
                                }
                            }
                        }
                    }

                    Button(action: onSaveManual) {
                        Text("保存地点")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(AppTheme.onPrimaryAction)
                            .frame(maxWidth: .infinity)
                            .frame(height: 50)
                            .background(AppTheme.primaryAction)
                            .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                }

                if let message {
                    Text(message)
                        .font(AppTheme.Typography.caption)
                        .foregroundStyle(AppTheme.textSecondary)
                }

                Spacer()
            }
            .padding(22)
            .background(AppTheme.background)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("清除", action: onClear)
                        .foregroundStyle(AppTheme.textSecondary)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("关闭") {
                        dismiss()
                    }
                    .foregroundStyle(AppTheme.text)
                }
            }
        }
    }
}

private struct LocationSuggestionRow: View {
    let label: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(AppTheme.textMuted)
                    .frame(width: 28, height: 28)

                Text(label)
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(AppTheme.text)
                    .lineLimit(1)

                Spacer()

                Image(systemName: "arrow.up.left")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(AppTheme.textMuted)
            }
            .padding(.horizontal, 12)
            .frame(height: 42)
            .background(AppTheme.card)
            .clipShape(RoundedRectangle(cornerRadius: AppTheme.Radius.chip, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("选择地点 \(label)")
        .accessibilityHint("设为当前决策地点")
    }
}

struct EmailLoginView: View {
    let authService: AuthAPIService
    let onDone: () -> Void

    @State private var email = AuthTokenStore.email ?? ""
    @State private var nickname = AuthTokenStore.displayName ?? ""
    @State private var code = ""
    @State private var codeSent = false
    @State private var isSubmitting = false
    @State private var message: String?

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 8) {
                    Text(AuthTokenStore.email == nil ? "邮箱登录" : "账号")
                        .font(.system(size: 24, weight: .semibold))
                        .foregroundStyle(AppTheme.text)

                    if let signedInEmail = AuthTokenStore.email {
                        Text(signedInEmail)
                            .font(.system(size: 15))
                            .foregroundStyle(AppTheme.textSecondary)
                        if let displayName = AuthTokenStore.displayName, !displayName.isEmpty {
                            Text("昵称：\(displayName)")
                                .font(.system(size: 15, weight: .medium))
                                .foregroundStyle(AppTheme.text)
                        }
                    } else {
                        Text("用验证码登录，设备上的记录会绑定到这个邮箱。")
                            .font(.system(size: 14))
                            .lineSpacing(4)
                            .foregroundStyle(AppTheme.textSecondary)
                    }
                }

                if AuthTokenStore.email == nil {
                    TextField("邮箱", text: $email)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .padding(.horizontal, 14)
                        .frame(height: 48)
                        .background(AppTheme.card)
                        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: 14, style: .continuous)
                                .stroke(AppTheme.border, lineWidth: 1)
                        )

                    if codeSent {
                        TextField("6 位验证码", text: $code)
                            .keyboardType(.numberPad)
                            .textContentType(.oneTimeCode)
                            .padding(.horizontal, 14)
                            .frame(height: 48)
                            .background(AppTheme.card)
                            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                            .overlay(
                                RoundedRectangle(cornerRadius: 14, style: .continuous)
                                    .stroke(AppTheme.border, lineWidth: 1)
                            )
                    }

                    Button {
                        submit()
                    } label: {
                        Text(codeSent ? "登录" : "获取验证码")
                            .font(.system(size: 17, weight: .semibold))
                            .frame(maxWidth: .infinity)
                            .frame(height: 50)
                            .foregroundStyle(AppTheme.onPrimaryAction)
                            .background(AppTheme.primaryAction)
                            .clipShape(Capsule())
                    }
                    .disabled(isSubmitting || email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || (codeSent && code.count < 6))
                    .opacity(isSubmitting ? 0.55 : 1)
                } else {
                    TextField("昵称", text: $nickname)
                        .textContentType(.nickname)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .padding(.horizontal, 14)
                        .frame(height: 48)
                        .background(AppTheme.card)
                        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: 14, style: .continuous)
                                .stroke(AppTheme.border, lineWidth: 1)
                        )

                    Button {
                        saveNickname()
                    } label: {
                        Text("保存昵称")
                            .font(.system(size: 17, weight: .semibold))
                            .frame(maxWidth: .infinity)
                            .frame(height: 50)
                            .foregroundStyle(AppTheme.onPrimaryAction)
                            .background(AppTheme.primaryAction)
                            .clipShape(Capsule())
                    }
                    .disabled(isSubmitting || nickname.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .opacity(isSubmitting ? 0.55 : 1)

                    Button(role: .destructive) {
                        logout()
                    } label: {
                        Text("退出登录")
                            .font(.system(size: 17, weight: .semibold))
                            .frame(maxWidth: .infinity)
                            .frame(height: 50)
                    }
                    .buttonStyle(.bordered)
                }

                if let message {
                    Text(message)
                        .font(.system(size: 13))
                        .foregroundStyle(AppTheme.textSecondary)
                }

                Spacer()
            }
            .padding(22)
            .background(AppTheme.background)
            .navigationTitle("")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("关闭") {
                        onDone()
                    }
                    .foregroundStyle(AppTheme.text)
                }
            }
        }
    }

    private func submit() {
        let trimmedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedEmail.isEmpty, !isSubmitting else { return }
        isSubmitting = true
        message = nil
        Task { @MainActor in
            do {
                if codeSent {
                    let account = try await authService.verify(email: trimmedEmail, code: code)
                    nickname = account.displayName
                    message = "已登录。"
                    onDone()
                } else {
                    try await authService.requestCode(email: trimmedEmail)
                    codeSent = true
                    message = "验证码已发送。"
                }
            } catch {
                message = "没成功：\(error.localizedDescription)"
            }
            isSubmitting = false
        }
    }

    private func saveNickname() {
        let trimmedNickname = nickname.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedNickname.isEmpty, !isSubmitting else { return }
        isSubmitting = true
        message = nil
        Task { @MainActor in
            do {
                let account = try await authService.updateDisplayName(trimmedNickname)
                nickname = account.displayName
                message = "昵称已保存。"
            } catch {
                message = "没成功：\(error.localizedDescription)"
            }
            isSubmitting = false
        }
    }

    private func logout() {
        isSubmitting = true
        Task { @MainActor in
            await authService.logout()
            email = ""
            nickname = ""
            code = ""
            codeSent = false
            isSubmitting = false
            message = "已退出。"
        }
    }
}

private struct AssistantAvatar: View {
    var body: some View {
        ZStack {
            Circle()
                .fill(AppTheme.card)
                .frame(width: 30, height: 30)
                .overlay(
                    Circle()
                        .stroke(AppTheme.border, lineWidth: 1)
                )

            Image(systemName: "sparkles")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(AppTheme.green)
        }
    }
}

private struct AssistantHeader: View {
    let name: String

    var body: some View {
        HStack(spacing: 10) {
            AssistantAvatar()

            Text(name)
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(AppTheme.textSecondary)
        }
    }
}

private struct AssistantIntroRow: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            AssistantHeader(name: "皮皮")

            Text("你在哪? 想做什么?")
                .font(.system(size: 17, weight: .medium))
                .lineSpacing(4)
                .foregroundStyle(AppTheme.text)
                .padding(.horizontal, 16)
                .padding(.vertical, 13)
                .background(AppTheme.card)
                .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 20, style: .continuous)
                        .stroke(AppTheme.border, lineWidth: 1)
                )
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct UserChatBubble: View {
    let text: String

    var body: some View {
        HStack {
            Spacer(minLength: 48)

            Text(text)
                .font(.system(size: 18))
                .lineSpacing(5)
                .foregroundStyle(AppTheme.text)
                .padding(.horizontal, 18)
                .padding(.vertical, 14)
                .background(AppTheme.bubble)
                .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
                .frame(maxWidth: 315, alignment: .trailing)
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("我, \(text)")
    }
}

private struct AssistantNoticeRow: View {
    let notice: ServiceNotice
    var actionTitle: String?
    var action: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            AssistantHeader(name: notice.title)

            VStack(alignment: .leading, spacing: 12) {
                Text(notice.detail)
                    .font(.system(size: 15))
                    .lineSpacing(4)
                    .foregroundStyle(AppTheme.text)

                if let actionTitle, let action {
                    Button(action: action) {
                        Text(actionTitle)
                            .font(.system(size: 14, weight: .semibold))
                            .foregroundStyle(AppTheme.text)
                            .frame(minWidth: 74)
                            .frame(height: 36)
                            .background(AppTheme.bubble)
                            .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(actionTitle)
                }
            }
            .padding(.horizontal, 15)
            .padding(.vertical, 12)
            .background(AppTheme.card)
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(AppTheme.border, lineWidth: 1)
            )
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct AssistantThinkingRow: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            AssistantHeader(name: "皮皮")

            HStack(spacing: 9) {
                ProgressView()
                    .tint(AppTheme.textMuted)
                    .scaleEffect(0.82)

                Text("正在想一个...")
                    .font(.system(size: 14))
                    .foregroundStyle(AppTheme.textSecondary)
            }
            .padding(.horizontal, 15)
            .padding(.vertical, 12)
            .background(AppTheme.card)
            .clipShape(Capsule())
            .overlay(
                Capsule()
                    .stroke(AppTheme.border, lineWidth: 1)
            )
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct AssistantRecommendationRow: View {
    let pick: TopPick
    let isAccepting: Bool
    let onAskHuman: () -> Void
    let onAccept: () -> Void
    let onFavorite: () -> Void
    let onChange: () -> Void
    let onReportIssue: () -> Void
    let onShare: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            AssistantHeader(name: "皮皮")
            ChatRecommendationCard(
                pick: pick,
                isAccepting: isAccepting,
                onAskHuman: onAskHuman,
                onAccept: onAccept,
                onFavorite: onFavorite,
                onChange: onChange,
                onReportIssue: onReportIssue,
                onShare: onShare
            )
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct AssistantHelpRow: View {
    let request: HelpRequest
    let isPublishing: Bool
    let onPublish: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            AssistantHeader(name: "皮皮")
            ChatHelpCard(request: request, isPublishing: isPublishing, onPublish: onPublish)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct ChatRecommendationCard: View {
    let pick: TopPick
    let isAccepting: Bool
    let onAskHuman: () -> Void
    let onAccept: () -> Void
    let onFavorite: () -> Void
    let onChange: () -> Void
    let onReportIssue: () -> Void
    let onShare: () -> Void

    @State private var hasAppeared = false
    @State private var acceptFeedbackCount = 0
    @State private var imageLoadFailed = false

    private var imageURL: URL? {
        guard !imageLoadFailed else { return nil }
        guard let url = pick.referenceImage?.url else { return nil }
        return URL(string: url)
    }

    private var decisionReason: String {
        let reason = pick.reason.trimmingCharacters(in: .whitespacesAndNewlines)
        if !reason.isEmpty {
            return reason
        }
        let subtitle = pick.subtitle.trimmingCharacters(in: .whitespacesAndNewlines)
        return subtitle.isEmpty ? "皮皮替你收成这一个。" : subtitle
    }

    private var supportingSubtitle: String? {
        let subtitle = pick.subtitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !subtitle.isEmpty, subtitle != decisionReason else { return nil }
        return subtitle
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            if imageURL != nil {
                heroImage
                    .overlay(alignment: .topTrailing) {
                        RecommendationOverflowMenu(
                            onFavorite: onFavorite,
                            onShare: onShare,
                            onChange: onChange,
                            onReportIssue: onReportIssue
                        )
                            .padding(12)
                    }
            } else {
                HStack {
                    Spacer()
                    RecommendationOverflowMenu(
                        onFavorite: onFavorite,
                        onShare: onShare,
                        onChange: onChange,
                        onReportIssue: onReportIssue
                    )
                }
            }

            VStack(alignment: .leading, spacing: 12) {
                if let supportingSubtitle {
                    Text(supportingSubtitle)
                        .font(.system(size: 15, weight: .medium))
                        .foregroundStyle(AppTheme.textSecondary)
                        .lineLimit(2)
                }

                Text(pick.title)
                    .font(.system(size: CardTextFitting.recommendationTitleSize(pick.title, hasImage: imageURL != nil, compact: true), weight: .bold))
                    .lineSpacing(3)
                    .foregroundStyle(AppTheme.text)
                    .lineLimit(3)
                    .minimumScaleFactor(0.72)

                Text(decisionReason)
                    .font(.system(size: 18, weight: .medium))
                    .lineSpacing(5)
                    .foregroundStyle(AppTheme.textSecondary)
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
            }

            HStack(spacing: 12) {
                Button(action: onAskHuman) {
                    Text("求一个")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(AppTheme.text)
                        .frame(maxWidth: .infinity)
                        .frame(height: 52)
                        .background(AppTheme.card)
                        .clipShape(Capsule())
                        .overlay(
                            Capsule()
                                .stroke(AppTheme.border, lineWidth: 1)
                        )
                }
                .buttonStyle(.plain)
                .accessibilityLabel("求一个")
                .accessibilityHint("把这个问题发给别人来一句")

                Button {
                    acceptFeedbackCount += 1
                    onAccept()
                } label: {
                    HStack(spacing: 8) {
                        if isAccepting {
                            ProgressView()
                                .tint(AppTheme.onPrimaryAction)
                                .scaleEffect(0.76)
                        }

                        Text(isAccepting ? "确认中" : "就这个")
                            .font(.system(size: 16, weight: .semibold))
                    }
                    .foregroundStyle(AppTheme.onPrimaryAction)
                    .frame(maxWidth: .infinity)
                    .frame(height: 52)
                    .background(AppTheme.primaryAction)
                    .clipShape(Capsule())
                    .animation(.spring(response: 0.22, dampingFraction: 0.88), value: isAccepting)
                }
                .buttonStyle(.plain)
                .disabled(isAccepting)
                .accessibilityLabel("就这个")
                .accessibilityHint("采纳皮皮给出的这个选择")
                .sensoryFeedback(.selection, trigger: acceptFeedbackCount)
            }
        }
        .padding(imageURL == nil ? 22 : 16)
        .padding(.bottom, 20)
        .frame(minHeight: imageURL == nil ? 270 : nil, alignment: .topLeading)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .stroke(AppTheme.border, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.055), radius: 22, x: 0, y: 12)
        .scaleEffect(hasAppeared ? 1 : 0.985)
        .opacity(hasAppeared ? 1 : 0)
        .offset(y: hasAppeared ? 0 : 8)
        .animation(.spring(response: 0.34, dampingFraction: 0.88), value: hasAppeared)
        .onAppear {
            hasAppeared = true
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("推荐卡, \(pick.title), \(decisionReason)")
    }

    @ViewBuilder
    private var heroImage: some View {
        if let imageURL {
            AsyncImage(url: imageURL) { phase in
                switch phase {
                case .success(let image):
                    image
                        .resizable()
                        .scaledToFill()
                case .failure:
                    Color.clear
                        .task {
                            withAnimation(.easeInOut(duration: 0.18)) {
                                imageLoadFailed = true
                            }
                        }
                case .empty:
                    RecommendationImageSkeleton()
                @unknown default:
                    Color.clear
                        .task {
                            withAnimation(.easeInOut(duration: 0.18)) {
                                imageLoadFailed = true
                            }
                        }
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: 228)
            .background(AppTheme.bubble)
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
            .accessibilityHidden(true)
        }
    }
}

private struct ChatHelpCard: View {
    let request: HelpRequest
    let isPublishing: Bool
    let onPublish: () -> Void

    @State private var publishFeedbackCount = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 15) {
            HStack(alignment: .center) {
                Text("求一个")
                    .font(.system(size: 12, weight: .medium))
                    .tracking(1.2)
                    .foregroundStyle(AppTheme.textMuted)

                Spacer()

                Text(request.status.label)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(AppTheme.textMuted)
            }

            VStack(alignment: .leading, spacing: 9) {
                Text(request.title)
                    .font(.system(size: CardTextFitting.requestTitleSize(request.title, compact: true), weight: .semibold))
                    .lineSpacing(3)
                    .foregroundStyle(AppTheme.text)
                    .lineLimit(3)
                    .minimumScaleFactor(0.82)

                CollapsibleText(
                    text: request.context,
                    font: .system(size: 14),
                    color: AppTheme.textSecondary,
                    collapsedLineLimit: 3,
                    lineSpacing: 4,
                    expandThreshold: 84
                )
            }

            HelpStructuredSummary(request: request, compact: true)

            if request.status == .draft {
                Button(action: publish) {
                    HStack(spacing: 8) {
                        if isPublishing {
                            ProgressView()
                                .tint(AppTheme.onPrimaryAction)
                                .scaleEffect(0.76)
                        }

                        Text(isPublishing ? "发出去中" : "发出去")
                            .font(.system(size: 15, weight: .medium))
                    }
                    .foregroundStyle(AppTheme.onPrimaryAction)
                    .frame(maxWidth: .infinity)
                    .frame(height: 50)
                    .background(AppTheme.primaryAction)
                    .clipShape(Capsule())
                }
                .buttonStyle(.plain)
                .disabled(isPublishing)
                .accessibilityLabel("发出去")
                .sensoryFeedback(.selection, trigger: publishFeedbackCount)
            } else {
                HStack(spacing: 8) {
                    Image(systemName: "paperplane")
                        .font(.system(size: 13, weight: .medium))

                    Text("已发出去")
                        .font(.system(size: 13, weight: .medium))
                }
                .foregroundStyle(AppTheme.textSecondary)
                .padding(.horizontal, 13)
                .padding(.vertical, 10)
                .background(AppTheme.bubble)
                .clipShape(Capsule())
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .stroke(AppTheme.border, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.04), radius: 14, x: 0, y: 8)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("求一个, \(request.title), \(request.context)")
    }

    private func publish() {
        guard !isPublishing else { return }
        publishFeedbackCount += 1
        onPublish()
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
    @State private var sharePayload: CardSharePayload?

    var body: some View {
        AppChrome(showsBack: true, backAction: onBackHome) {
            ScrollView {
                VStack(spacing: 0) {
                    QueryBubble(text: session.currentQuery.isEmpty ? MockData.queryPlaceholder : session.currentQuery)

                    if let notice = session.serviceNotice {
                        ServiceNoticePill(notice: notice)
                            .padding(.bottom, 12)
                    }

                    DecisionCard(
                        pick: session.topPick,
                        isFollowingUp: isFollowingUp,
                        isAccepting: isAccepting,
                        onFollowup: followUp,
                        onAskHuman: askHuman,
                        onReject: changePick,
                        onFavorite: favoritePick,
                        onReportIssue: reportPickIssue,
                        onShare: sharePick,
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
        .sheet(item: $sharePayload) { payload in
            ActivityShareSheet(items: [payload.text])
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
        let baseQuery = session.currentQuery.isEmpty ? MockData.queryPlaceholder : session.currentQuery
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
            AppHaptics.success()
            isAccepting = false
            onAccepted()
        }
    }

    private func askHuman() {
        AppHaptics.selection()
        Task {
            _ = await session.sendCurrentTopPickFeedback(action: .askHuman, reason: "想听真人意见")
        }
        onAskHuman()
    }

    private func favoritePick() {
        AppHaptics.success()
        session.saveCurrentTopPickToFavorites()
    }

    private func changePick() {
        AppHaptics.selection()
        Task {
            _ = await session.sendCurrentTopPickFeedback(action: .change, reason: "不合适，想换一个")
        }
        followUp("不合适，换一个")
    }

    private func reportPickIssue() {
        AppHaptics.warning()
        Task {
            _ = await session.sendCurrentTopPickFeedback(action: .reject, reason: "信息有误")
        }
    }

    private func sharePick() {
        AppHaptics.selection()
        sharePayload = CardSharePayload(text: shareText(for: session.topPick))
    }

    private func shareText(for pick: TopPick) -> String {
        let reason = pick.reason.trimmingCharacters(in: .whitespacesAndNewlines)
        let subtitle = pick.subtitle.trimmingCharacters(in: .whitespacesAndNewlines)
        let detail = reason.isEmpty ? subtitle : reason
        guard !detail.isEmpty else { return "\(pick.title)\n来自皮皮" }
        return "\(pick.title)\n\(detail)\n来自皮皮"
    }
}

struct AskScreen: View {
    let session: AppSession
    let onHome: () -> Void

    @State private var draft = ""
    @State private var isPublishing = false
    @State private var toastMessage = "发出去了，等别人来一句。"
    @State private var showsToast = false
    @State private var publishFeedbackCount = 0
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
        .sensoryFeedback(.selection, trigger: publishFeedbackCount)
    }

    private func publish() {
        guard session.helpRequest.status == .draft, !isPublishing else { return }
        publishFeedbackCount += 1
        isPublishing = true
        publishTask?.cancel()
        publishTask = Task { @MainActor in
            await session.publishCurrentRequest()
            AppHaptics.success()
            isPublishing = false
            toastMessage = "发出去了，等别人来一句。"
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
            AppHaptics.success()
            onHome()
        }
    }
}

struct AnswerScreen: View {
    let session: AppSession
    var showsTopBar: Bool = true

    @Environment(\.dismiss) private var dismiss
    @State private var draft = ""
    @State private var isLoading = true
    @State private var isSending = false
    @State private var showsToast = false
    @State private var toastMessage = "收到了，+10 等她采纳。"
    @State private var toastTask: Task<Void, Never>?
    @State private var isComposerFocused = false

    var body: some View {
        AppChrome(showsBack: true, backAction: nil, showsTopBar: showsTopBar) {
            GeometryReader { proxy in
                ZStack {
                    ScrollView {
                        VStack(spacing: 0) {
                            VStack(alignment: .leading, spacing: 5) {
                                Text("来一句")
                                    .font(.system(size: 24, weight: .semibold))
                                    .foregroundStyle(AppTheme.text)

                                Text("帮 TA 少纠结一次。")
                                    .font(.system(size: 14))
                                    .foregroundStyle(AppTheme.textSecondary)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 8)
                            .padding(.top, 8)
                            .padding(.bottom, 14)

                            HelpDeckStack(
                                current: session.answerRequest,
                                next: session.nextAnswerRequest,
                                isLoading: isLoading,
                                onAdvance: {
                                    session.advanceAnswerRequest()
                                },
                                onHideCurrent: {
                                    session.advanceAnswerRequest()
                                    toastMessage = "已跳过这张。"
                                    flashToast()
                                },
                                onReportCurrent: {
                                    toastMessage = "收到，已标记这张求一个。"
                                    flashToast()
                                },
                                onRefresh: {
                                    Task { @MainActor in
                                        await reloadAnswerQueue()
                                    }
                                },
                                onBackToChat: {
                                    dismiss()
                                }
                            )
                            .frame(height: max(proxy.size.height - 92, 460))

                            Spacer(minLength: 18)
                        }
                        .padding(.horizontal, 14)
                        .padding(.bottom, 14)
                        .frame(minHeight: proxy.size.height)
                        .contentShape(Rectangle())
                        .onTapGesture {
                            dismissKeyboard()
                        }
                    }
                    .scrollIndicators(.hidden)
                    .scrollDismissesKeyboard(.interactively)
                    .simultaneousGesture(
                        DragGesture(minimumDistance: 8)
                            .onChanged { _ in dismissKeyboard() }
                    )
                    .refreshable {
                        await reloadAnswerQueue()
                    }

                    ToastView(message: toastMessage, isVisible: showsToast)
                }
            }
        } footer: {
            BottomComposer(
                text: $draft,
                placeholder: answerPlaceholder,
                focused: $isComposerFocused,
                isSending: isSending || session.answerRequest == nil
            ) {
                sendAnswer()
            }
        }
        .task {
            await reloadAnswerQueue()
        }
        .onDisappear {
            toastTask?.cancel()
        }
    }

    private func sendAnswer() {
        let answer = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard answer.count >= 2, let request = session.answerRequest else {
            AppHaptics.warning()
            toastMessage = "至少写两个字。"
            flashToast()
            return
        }
        draft = ""
        dismissKeyboard()
        toastTask?.cancel()
        isSending = true
        toastMessage = "收到了，\(request.rewardLabel) 等她采纳。"
        toastTask = Task { @MainActor in
            await session.addAnswer(answer)
            AppHaptics.success()
            isSending = false
            showsToast = true
            try? await Task.sleep(for: .milliseconds(1_600))
            guard !Task.isCancelled else { return }
            showsToast = false
        }
    }

    private func reloadAnswerQueue() async {
        isLoading = true
        await session.loadAnswerQueue()
        isLoading = false
    }

    private func flashToast() {
        toastTask?.cancel()
        showsToast = true
        toastTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(1_200))
            guard !Task.isCancelled else { return }
            showsToast = false
        }
    }

    private var answerPlaceholder: String {
        guard let request = session.answerRequest else {
            return "等下一张求一个"
        }
        let title = request.title.trimmingCharacters(in: .whitespacesAndNewlines)
        if title.contains("明洞") || title.contains("韩国") || title.contains("小众") {
            return "别去明洞当背景板，去圣水。"
        }
        if title.contains("海底捞") || title.contains("不辣") {
            return "番茄锅更稳，别上红油。"
        }
        return "来一句，帮 TA 少纠结"
    }

    private func dismissKeyboard() {
        isComposerFocused = false
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
    }
}

struct HelpDeckStack: View {
    let current: HelpRequest?
    let next: HelpRequest?
    let isLoading: Bool
    let onAdvance: () -> Void
    let onHideCurrent: () -> Void
    let onReportCurrent: () -> Void
    let onRefresh: () -> Void
    let onBackToChat: () -> Void

    @State private var dragOffset: CGFloat = 0
    @State private var committedSwipeCount = 0

    var body: some View {
        GeometryReader { proxy in
            let cardWidth = min(proxy.size.width - 30, 390)
            let cardHeight = min(max(proxy.size.height * 0.78, 420), 560)
            let dragProgress = min(abs(dragOffset) / max(cardWidth * 0.42, 1), 1)

            ZStack {
                if isLoading {
                    HelpDeckLoadingCard()
                        .frame(width: cardWidth, height: cardHeight)
                } else if let current {
                    if let next {
                        HelpDeckCard(request: next)
                            .frame(width: cardWidth, height: cardHeight)
                            .scaleEffect(0.95 + 0.03 * dragProgress)
                            .offset(x: dragOffset >= 0 ? -28 + 10 * dragProgress : 24 - 10 * dragProgress)
                            .opacity(0.52 + 0.18 * dragProgress)
                            .allowsHitTesting(false)
                    }

                    HelpDeckCard(
                        request: current,
                        showsMenu: true,
                        onHide: onHideCurrent,
                        onReport: onReportCurrent
                    )
                        .frame(width: cardWidth, height: cardHeight)
                        .offset(x: dragOffset)
                        .scaleEffect(1 - 0.035 * dragProgress)
                        .rotationEffect(.degrees(Double(dragOffset / 36)))
                        .gesture(
                            DragGesture()
                                .onChanged { value in
                                    dragOffset = value.translation.width
                                }
                                .onEnded { value in
                                    if abs(value.translation.width) > 90 {
                                        withAnimation(.spring(response: 0.28, dampingFraction: 0.82)) {
                                            dragOffset = value.translation.width > 0 ? cardWidth : -cardWidth
                                        }
                                        committedSwipeCount += 1
                                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.16) {
                                            onAdvance()
                                            withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
                                                dragOffset = 0
                                            }
                                        }
                                    } else {
                                        withAnimation(.spring(response: 0.32, dampingFraction: 0.84)) {
                                            dragOffset = 0
                                        }
                                    }
                                }
                        )
                } else {
                    EmptyAnswerQueueCard(onRefresh: onRefresh, onBackToChat: onBackToChat)
                        .frame(width: cardWidth)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .sensoryFeedback(.selection, trigger: committedSwipeCount)
        }
    }
}

struct HelpDeckCard: View {
    let request: HelpRequest
    var showsMenu = false
    var onHide: () -> Void = {}
    var onReport: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .center) {
                Text("求一个")
                    .font(.system(size: 13, weight: .semibold))
                    .tracking(1.2)
                    .foregroundStyle(AppTheme.textMuted)

                Spacer()

                Text(request.rewardLabel)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(AppTheme.green)

                if showsMenu {
                    Menu {
                        Button(role: .destructive, action: onReport) {
                            Label("举报这张", systemImage: "exclamationmark.bubble")
                        }
                        Button(action: onHide) {
                            Label("屏蔽这张", systemImage: "eye.slash")
                        }
                    } label: {
                        Image(systemName: "ellipsis")
                            .font(.system(size: 18, weight: .semibold))
                            .foregroundStyle(AppTheme.textSecondary)
                            .frame(width: 44, height: 44)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("更多求助操作")
                }
            }

            Spacer(minLength: 24)

            Text(request.title)
                .font(.system(size: CardTextFitting.requestTitleSize(request.title) + 8, weight: .semibold))
                .lineSpacing(4)
                .foregroundStyle(AppTheme.text)
                .lineLimit(3)
                .minimumScaleFactor(0.76)
                .frame(maxWidth: .infinity, alignment: .leading)
                .multilineTextAlignment(.leading)

            Text(request.context)
                .font(.system(size: 17))
                .lineSpacing(6)
                .foregroundStyle(AppTheme.textSecondary)
                .lineLimit(3)
                .multilineTextAlignment(.leading)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 18)

            HelpStructuredSummary(request: request, compact: true)
                .padding(.top, 20)

            Spacer(minLength: 26)

            HStack(spacing: 8) {
                Text(request.answerCount > 0 ? "\(request.answerCount) 人已答" : "看懂了，就来一句。")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(AppTheme.textSecondary)

                Spacer()
            }
        }
        .padding(24)
        .background(AppTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .stroke(AppTheme.border, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.055), radius: 22, x: 0, y: 12)
        .accessibilityElement(children: showsMenu ? .contain : .combine)
        .accessibilityLabel("求一个, \(request.title), \(request.rewardLabel)")
        .accessibilityHint("左右滑动切换求助，底部输入框可以来一句")
    }
}

struct HelpDeckLoadingCard: View {
    @State private var isBreathing = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Capsule()
                    .fill(skeletonFill)
                    .frame(width: 58, height: 13)

                Spacer()

                Capsule()
                    .fill(skeletonFill)
                    .frame(width: 42, height: 13)
            }

            Spacer(minLength: 28)

            VStack(alignment: .leading, spacing: 14) {
                skeletonBlock(height: 34, trailing: 26)
                skeletonBlock(height: 34, trailing: 68)
                skeletonBlock(height: 16, trailing: 34)
                    .padding(.top, 8)
                skeletonBlock(height: 16, trailing: 82)
            }

            VStack(alignment: .leading, spacing: 12) {
                skeletonBlock(height: 28, trailing: 112)
                skeletonBlock(height: 28, trailing: 66)
                skeletonBlock(height: 28, trailing: 138)
            }
            .padding(.top, 28)

            Spacer(minLength: 28)

            Capsule()
                .fill(skeletonFill)
                .frame(width: 152, height: 14)
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(AppTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .stroke(AppTheme.border, lineWidth: 1)
        )
        .onAppear {
            withAnimation(.easeInOut(duration: 0.95).repeatForever(autoreverses: true)) {
                isBreathing = true
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("正在取求一个")
    }

    private var skeletonFill: Color {
        AppTheme.textMuted.opacity(isBreathing ? 0.16 : 0.08)
    }

    private func skeletonBlock(height: CGFloat, trailing: CGFloat) -> some View {
        Capsule()
            .fill(skeletonFill)
            .frame(maxWidth: .infinity)
            .frame(height: height)
            .padding(.trailing, trailing)
    }
}

struct ServiceNoticePill: View {
    let notice: ServiceNotice

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: notice.title == "皮皮" ? "quote.bubble" : "exclamationmark.triangle")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(notice.title == "皮皮" ? AppTheme.textSecondary : AppTheme.orangeText)
                .padding(.top, 1)

            VStack(alignment: .leading, spacing: 2) {
                Text(notice.title)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(notice.title == "皮皮" ? AppTheme.text : AppTheme.orangeText)

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
        .background(notice.title == "皮皮" ? AppTheme.card : AppTheme.orangeBackground)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(notice.title), \(notice.detail)")
    }
}

struct EmptyAnswerQueueCard: View {
    let onRefresh: () -> Void
    let onBackToChat: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("暂时没有求一个")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(AppTheme.text)

            Text("晚点再来，或者自己发一个。")
                .font(.system(size: 14))
                .lineSpacing(4)
                .foregroundStyle(AppTheme.textSecondary)

            HStack(spacing: 12) {
                Button(action: onRefresh) {
                    Text("刷新")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(AppTheme.text)
                        .frame(maxWidth: .infinity)
                        .frame(height: 48)
                        .background(AppTheme.card)
                        .clipShape(Capsule())
                        .overlay(
                            Capsule()
                                .stroke(AppTheme.border, lineWidth: 1)
                        )
                }
                .buttonStyle(.plain)

                Button(action: onBackToChat) {
                    Text("回聊天")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(AppTheme.onPrimaryAction)
                        .frame(maxWidth: .infinity)
                        .frame(height: 48)
                        .background(AppTheme.primaryAction)
                        .clipShape(Capsule())
                }
                .buttonStyle(.plain)
            }
            .padding(.top, 6)
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


struct ProfileScreen: View {
    let session: AppSession
    let authRevision: Int
    let onManageAccount: () -> Void
    let onAuthChanged: () -> Void
    let onHistorySelect: (QuestionHistory) -> Void
    let onOpenAnswerDeck: () -> Void

    @State private var snapshot = UserDashboardSnapshot.empty
    @State private var isLoading = false
    @State private var isAccountActionRunning = false
    @State private var accountActionMessage: String?
    @State private var showsDeleteAccountConfirmation = false

    private var signedIn: Bool {
        AuthTokenStore.email != nil
    }

    private var displayName: String {
        if let name = AuthTokenStore.displayName?.trimmingCharacters(in: .whitespacesAndNewlines), !name.isEmpty {
            return name
        }
        return signedIn ? "已登录" : "登录后同步记录"
    }

    private var accountSubtitle: String {
        AuthTokenStore.email ?? "邮箱验证码登录"
    }

    private var myHelpHistory: [QuestionHistory] {
        session.history.filter { item in
            item.helpRequestId != nil || item.status == "waiting_for_human" || item.status == "answer_received"
        }
    }

    private var recentChoices: [QuestionHistory] {
        session.history.filter { item in
            item.status == "top1" || item.status == "completed"
        }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                accountCard
                metricGrid
                answerCallout

                profileHistorySection(
                    title: "我的求一个",
                    items: Array(myHelpHistory.prefix(3)),
                    emptyText: "还没有发过求一个"
                )

                profileHistorySection(
                    title: "最近选择",
                    items: Array(recentChoices.prefix(4)),
                    emptyText: "你的选择会出现在这里"
                )

                messageSection
                appInfoSection
            }
            .padding(.horizontal, 18)
            .padding(.top, 12)
            .padding(.bottom, 32)
        }
        .background(AppTheme.background.ignoresSafeArea())
        .navigationTitle("我的")
        .navigationBarTitleDisplayMode(.large)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                ProductRefreshToolbarButton(isLoading: isLoading) {
                    Task { await loadSnapshot() }
                }
            }
        }
        .refreshable {
            await loadSnapshot()
        }
        .task(id: authRevision) {
            await loadSnapshot()
        }
        .confirmationDialog("删除账号？", isPresented: $showsDeleteAccountConfirmation, titleVisibility: .visible) {
            Button("删除账号", role: .destructive) {
                deleteAccount()
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text("会清除当前邮箱登录、撤销会话，并把账号标记为已删除。这个操作不能在 App 内撤回。")
        }
    }

    private var accountCard: some View {
        Button(action: onManageAccount) {
            HStack(spacing: 15) {
                ZStack {
                    Circle()
                        .fill(AppTheme.bubble)
                        .frame(width: 54, height: 54)

                    Image(systemName: signedIn ? "person.crop.circle.fill" : "person.crop.circle")
                        .font(.system(size: 28, weight: .medium))
                        .foregroundStyle(AppTheme.text)
                }

                VStack(alignment: .leading, spacing: 5) {
                    Text(displayName)
                        .font(.system(size: 19, weight: .semibold))
                        .foregroundStyle(AppTheme.text)

                    Text(accountSubtitle)
                        .font(.system(size: 14))
                        .foregroundStyle(AppTheme.textSecondary)
                        .lineLimit(1)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(AppTheme.textMuted)
            }
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(AppTheme.card)
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .stroke(AppTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(signedIn ? "管理账号" : "邮箱登录")
    }

    private var metricGrid: some View {
        HStack(spacing: 10) {
            ProfileMetricTile(
                value: "\(snapshot.grantedReward)",
                label: "已得积分",
                secondary: snapshot.pendingReward > 0 ? "+\(snapshot.pendingReward) 待确认" : nil
            )
            ProfileMetricTile(
                value: "\(snapshot.answeredCount)",
                label: "来过一句",
                secondary: qualityTierLabel
            )
            ProfileMetricTile(
                value: "\(session.history.count)",
                label: "历史选择",
                secondary: nil
            )
        }
    }

    private var answerCallout: some View {
        Button(action: onOpenAnswerDeck) {
            HStack(spacing: 14) {
                Image(systemName: "bubble.left.and.bubble.right.fill")
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(AppTheme.onPrimaryAction)
                    .frame(width: 44, height: 44)
                    .background(AppTheme.primaryAction)
                    .clipShape(Circle())

                VStack(alignment: .leading, spacing: 4) {
                    Text("来一句")
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(AppTheme.text)
                    Text("刷一张求一个，顺手帮 TA 少纠结一次。")
                        .font(.system(size: 13))
                        .foregroundStyle(AppTheme.textSecondary)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(AppTheme.textMuted)
            }
            .padding(16)
            .background(AppTheme.card)
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .stroke(AppTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private func profileHistorySection(title: String, items: [QuestionHistory], emptyText: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            ProfileSectionHeader(title: title)

            if items.isEmpty {
                ProductEmptyInline(title: emptyText, message: "有内容后会自动归档在这里。")
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(items.enumerated()), id: \.element.id) { index, item in
                        Button {
                            onHistorySelect(item)
                        } label: {
                            ProfileHistoryRow(item: item)
                        }
                        .buttonStyle(.plain)

                        if index < items.count - 1 {
                            Divider()
                                .padding(.leading, 16)
                        }
                    }
                }
                .background(AppTheme.card)
                .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 20, style: .continuous)
                        .stroke(AppTheme.border, lineWidth: 1)
                )
            }
        }
    }

    private var messageSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            ProfileSectionHeader(title: "消息")

            if snapshot.lightEvents.isEmpty {
                ProductEmptyInline(title: "暂时没有新消息", message: "有人回答、结果完成或奖励变化时会出现在这里。")
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(snapshot.lightEvents.prefix(3).enumerated()), id: \.element.id) { index, event in
                        ProfileMessageRow(event: event)
                        if index < min(snapshot.lightEvents.count, 3) - 1 {
                            Divider()
                                .padding(.leading, 52)
                        }
                    }
                }
                .background(AppTheme.card)
                .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 20, style: .continuous)
                        .stroke(AppTheme.border, lineWidth: 1)
                )
            }
        }
    }

    private var appInfoSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            ProfileSectionHeader(title: "设置")

            VStack(spacing: 0) {
                Button(action: onManageAccount) {
                    HStack(spacing: 12) {
                        Image(systemName: "person.crop.circle")
                            .font(.system(size: 17, weight: .semibold))
                            .foregroundStyle(AppTheme.text)
                            .frame(width: 24)

                        VStack(alignment: .leading, spacing: 3) {
                            Text(signedIn ? "账号与登录" : "登录并同步")
                                .font(.system(size: 15, weight: .medium))
                                .foregroundStyle(AppTheme.text)
                            Text(accountSubtitle)
                                .font(.system(size: 12))
                                .foregroundStyle(AppTheme.textMuted)
                                .lineLimit(1)
                        }

                        Spacer()
                        Image(systemName: "chevron.right")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(AppTheme.textMuted)
                    }
                    .padding(16)
                }
                .buttonStyle(.plain)

                Divider()
                    .padding(.leading, 16)

                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: "hand.raised")
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(AppTheme.text)
                        .frame(width: 24)

                    VStack(alignment: .leading, spacing: 4) {
                        Text("隐私与数据")
                            .font(.system(size: 15, weight: .medium))
                            .foregroundStyle(AppTheme.text)
                        Text("只用于同步你的选择、求助、回答和奖励；不会在产品界面展示调试日志。")
                            .font(.system(size: 12))
                            .foregroundStyle(AppTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    Spacer()
                }
                .padding(16)

                if signedIn {
                    Divider()
                        .padding(.leading, 16)

                    Button {
                        logoutAccount()
                    } label: {
                        HStack(spacing: 12) {
                            Image(systemName: "rectangle.portrait.and.arrow.right")
                                .font(.system(size: 17, weight: .semibold))
                                .frame(width: 24)
                            Text("退出登录")
                                .font(.system(size: 15, weight: .medium))
                            Spacer()
                            if isAccountActionRunning {
                                ProgressView()
                                    .tint(AppTheme.textSecondary)
                            }
                        }
                        .foregroundStyle(AppTheme.text)
                        .padding(16)
                    }
                    .buttonStyle(.plain)
                    .disabled(isAccountActionRunning)

                    Divider()
                        .padding(.leading, 16)

                    Button(role: .destructive) {
                        showsDeleteAccountConfirmation = true
                    } label: {
                        HStack(spacing: 12) {
                            Image(systemName: "trash")
                                .font(.system(size: 17, weight: .semibold))
                                .frame(width: 24)
                            Text("删除账号")
                                .font(.system(size: 15, weight: .medium))
                            Spacer()
                        }
                        .padding(16)
                    }
                    .buttonStyle(.plain)
                    .disabled(isAccountActionRunning)
                }

                if let accountActionMessage {
                    Divider()
                        .padding(.leading, 16)

                    Text(accountActionMessage)
                        .font(.system(size: 13))
                        .foregroundStyle(AppTheme.textSecondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(16)
                }

                Divider()
                    .padding(.leading, 16)

                HStack {
                    Label("版本", systemImage: "info.circle")
                        .font(.system(size: 15, weight: .medium))
                        .foregroundStyle(AppTheme.text)
                    Spacer()
                    Text(appVersion)
                        .font(.system(size: 14))
                        .foregroundStyle(AppTheme.textSecondary)
                }
                .padding(16)
            }
            .background(AppTheme.card)
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .stroke(AppTheme.border, lineWidth: 1)
            )
        }
    }

    private var qualityTierLabel: String? {
        switch snapshot.qualityTier {
        case "reliable": "靠谱答主"
        case "promising": "正在变靠谱"
        case "at_risk": "需要更认真"
        default: nil
        }
    }

    private var appVersion: String {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.1.0"
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "1"
        return "\(version) (\(build))"
    }

    @MainActor
    private func loadSnapshot() async {
        guard !isLoading else { return }
        isLoading = true
        snapshot = await ProfileAPIService().fetchSnapshot()
        isLoading = false
    }

    private func logoutAccount() {
        guard !isAccountActionRunning else { return }
        isAccountActionRunning = true
        accountActionMessage = nil
        Task {
            await AuthAPIService().logout()
            await MainActor.run {
                snapshot = .empty
                isAccountActionRunning = false
                accountActionMessage = "已退出登录。"
                onAuthChanged()
            }
        }
    }

    private func deleteAccount() {
        guard !isAccountActionRunning else { return }
        isAccountActionRunning = true
        accountActionMessage = nil
        Task {
            do {
                try await AuthAPIService().deleteAccount()
                await MainActor.run {
                    snapshot = .empty
                    isAccountActionRunning = false
                    accountActionMessage = "账号已删除，本机登录已清除。"
                    onAuthChanged()
                }
            } catch {
                await MainActor.run {
                    isAccountActionRunning = false
                    accountActionMessage = "删除失败，请稍后再试。"
                }
            }
        }
    }
}

struct MyHelpScreen: View {
    let session: AppSession
    let onSelectHelpDetail: (QuestionHistory) -> Void

    private var helpItems: [QuestionHistory] {
        session.history.filter { item in
            item.helpRequestId != nil
            || item.status == "waiting_for_human"
            || item.status == "answer_received"
            || item.status == "closed"
        }
    }

    private var currentDraft: HelpRequest? {
        guard session.currentHelpRequest?.status == .draft else { return nil }
        return session.currentHelpRequest
    }

    private var draftCount: Int {
        currentDraft == nil ? 0 : 1
    }

    private var collectingCount: Int {
        helpItems.filter { $0.status == "waiting_for_human" }.count
    }

    private var answeredCount: Int {
        helpItems.filter { $0.status == "answer_received" }.count
    }

    private var completedCount: Int {
        helpItems.filter { $0.status == "completed" || $0.status == "top1" }.count
    }

    private var closedCount: Int {
        helpItems.filter { $0.status == "closed" }.count
    }

    private var statusColumns: [GridItem] {
        [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)]
    }

    var body: some View {
        ProductListScreen(
            title: "我的求一个",
            subtitle: "草稿、收集中和已有结果都在这里。",
            systemImage: "questionmark.bubble",
            emptyTitle: "还没有求一个",
            emptyMessage: "在聊天里点“求一个”，发出去后就会出现在这里。",
            isEmpty: currentDraft == nil && helpItems.isEmpty
        ) {
            ProductSection(title: "状态") {
                LazyVGrid(columns: statusColumns, spacing: 10) {
                    ProfileMetricTile(value: "\(draftCount)", label: "草稿", secondary: draftCount > 0 ? "待发布" : nil)
                    ProfileMetricTile(value: "\(collectingCount)", label: "收集中", secondary: collectingCount > 0 ? "等来一句" : nil)
                    ProfileMetricTile(value: "\(answeredCount)", label: "已有结果", secondary: answeredCount > 0 ? "可查看" : nil)
                    ProfileMetricTile(
                        value: "\(completedCount)",
                        label: "已完成",
                        secondary: closedCount > 0 ? "\(closedCount) 已关闭" : nil
                    )
                }
            }

            if let currentDraft {
                ProductSection(title: "草稿") {
                    RequestCard(request: currentDraft)
                }
            }

            if !helpItems.isEmpty {
                ProductSection(title: "求助记录") {
                    VStack(spacing: 0) {
                        ForEach(Array(helpItems.enumerated()), id: \.element.id) { index, item in
                            Button {
                                onSelectHelpDetail(item)
                            } label: {
                                ProfileHistoryRow(item: item)
                            }
                            .buttonStyle(.plain)

                            if index < helpItems.count - 1 {
                                Divider()
                                    .padding(.leading, 16)
                            }
                        }
                    }
                    .productPanel()
                }
            }
        }
    }
}

struct HelpResultDetailScreen: View {
    let session: AppSession
    let historyItem: QuestionHistory

    @State private var request: HelpRequest?
    @State private var isLoading = false

    private var displayRequest: HelpRequest {
        request ?? initialRequest
    }

    private var humanAnswers: [HumanAnswer] {
        displayRequest.answers.filter { $0.nickname != "皮皮" }
    }

    private var pipiAnswer: HumanAnswer? {
        displayRequest.answers.first { $0.nickname == "皮皮" }
    }

    private var initialRequest: HelpRequest {
        HelpRequest(
            id: historyItem.helpRequestId ?? historyItem.id,
            title: historyItem.query,
            context: historyItem.topPick?.reason ?? historyItem.statusLabel,
            status: status(from: historyItem.status),
            answers: []
        )
    }

    var body: some View {
        ProductListScreen(
            title: "求助详情",
            subtitle: "看人类回答和皮皮最后帮你收口的选择。",
            systemImage: "questionmark.bubble",
            emptyTitle: "还没有求助详情",
            emptyMessage: "这条求助还在同步。",
            isEmpty: false
        ) {
            ProductSection(title: "求助内容") {
                HelpDetailSummaryPanel(request: displayRequest, isLoading: isLoading)
            }

            ProductSection(title: "人类回答") {
                if humanAnswers.isEmpty {
                    ProductEmptyInline(
                        title: displayRequest.answerCount > 0 ? "已有 \(displayRequest.answerCount) 句，正在同步" : "还在等来一句",
                        message: "有新回答后会出现在这里，你不用看任何 Agent 日志。"
                    )
                } else {
                    VStack(spacing: 12) {
                        ForEach(humanAnswers) { answer in
                            HelpAnswerDetailRow(answer: answer)
                        }
                    }
                    .productPanel()
                }
            }

            ProductSection(title: "皮皮最终推荐") {
                if let pick = historyItem.topPick {
                    HelpFinalRecommendationPanel(pick: pick)
                } else if let pipiAnswer {
                    HelpFinalTextPanel(answer: pipiAnswer)
                } else {
                    ProductEmptyInline(
                        title: displayRequest.status == .answered || displayRequest.status == .completed ? "结果快好了" : "还没形成最终推荐",
                        message: "等回答足够后，皮皮会把来一句合成一个最终选择。"
                    )
                }
            }
        }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    Task { await loadDetail() }
                } label: {
                    if isLoading {
                        ProgressView()
                            .tint(AppTheme.text)
                    } else {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 16, weight: .semibold))
                    }
                }
                .disabled(isLoading)
                .accessibilityLabel("刷新求助详情")
            }
        }
        .task(id: historyItem.id) {
            await loadDetail()
        }
    }

    @MainActor
    private func loadDetail() async {
        guard !isLoading else { return }
        isLoading = true
        request = await session.helpRequestDetail(for: historyItem)
        isLoading = false
    }

    private func status(from raw: String) -> HelpRequestStatus {
        switch raw {
        case "completed", "top1":
            .completed
        case "answer_received":
            .answered
        case "waiting_for_human":
            .published
        default:
            .draft
        }
    }
}

struct MyAnswersScreen: View {
    let session: AppSession
    let onOpenAnswerDeck: () -> Void

    @State private var snapshot = UserDashboardSnapshot.empty
    @State private var isLoading = false

    private var localPendingAnswers: [SubmittedAnswerRecord] {
        session.submittedAnswers.filter { $0.status == .pending }
    }

    private var pendingAnswerCount: Int {
        max(
            localPendingAnswers.count,
            snapshot.rewardStatusCounts["pending"] ?? 0,
            snapshot.answerStatusCounts["submitted"] ?? 0
        )
    }

    private var acceptedAnswerCount: Int {
        snapshot.rewardStatusCounts["granted"] ?? 0
    }

    private var rejectedAnswerCount: Int {
        snapshot.rewardStatusCounts["rejected"] ?? 0
    }

    private var submittedCount: Int {
        max(snapshot.answeredCount, session.submittedAnswers.count)
    }

    var body: some View {
        ProductListScreen(
            title: "我的回答",
            subtitle: "看你来过的一句，以及还有哪些题可以顺手帮忙。",
            systemImage: "quote.bubble",
            emptyTitle: "还没来过一句",
            emptyMessage: "去来一句 Deck，写完后待采纳和奖励会显示在这里。",
            isEmpty: false
        ) {
            ProductSection(title: "状态") {
                HStack(spacing: 10) {
                    ProfileMetricTile(
                        value: "\(pendingAnswerCount)",
                        label: "待采纳",
                        secondary: pendingAnswerCount > 0 ? "\(snapshot.pendingReward) 待确认" : answerTierLabel
                    )
                    ProfileMetricTile(
                        value: "\(acceptedAnswerCount)",
                        label: "已采纳",
                        secondary: acceptedAnswerCount > 0 ? "+\(snapshot.grantedReward)" : nil
                    )
                    ProfileMetricTile(
                        value: "\(rejectedAnswerCount)",
                        label: "未采用",
                        secondary: rejectedAnswerCount > 0 ? "+\(snapshot.rejectedReward)" : nil
                    )
                }
            }

            ProductSection(title: "总览") {
                ProductActionCard(
                    icon: "checkmark.bubble",
                    title: "已提交 \(submittedCount) 句",
                    subtitle: "待采纳、已采纳和未采用都会在这里归档。"
                )
            }

            ProductSection(title: "继续帮别人") {
                Button(action: onOpenAnswerDeck) {
                    ProductActionCard(
                        icon: "bubble.left.and.bubble.right.fill",
                        title: "打开来一句",
                        subtitle: "一屏一张求助卡，写一句就切下一张。"
                    )
                }
                .buttonStyle(.plain)
            }

            if !session.submittedAnswers.isEmpty {
                ProductSection(title: "最近提交") {
                    VStack(spacing: 12) {
                        ForEach(session.submittedAnswers) { answer in
                            SubmittedAnswerRow(answer: answer)
                        }
                    }
                }
            }

            if !session.answerQueue.isEmpty {
                ProductSection(title: "可回答") {
                    VStack(spacing: 12) {
                        ForEach(session.answerQueue.prefix(3)) { request in
                            AnswerRequestSquareCard(request: request, reward: request.rewardLabel)
                        }
                    }
                }
            }
        }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                ProductRefreshToolbarButton(isLoading: isLoading) {
                    Task { await loadSnapshot() }
                }
            }
        }
        .refreshable {
            await loadSnapshot()
        }
        .task {
            await loadSnapshot()
            await session.loadAnswerQueue()
        }
    }

    private var answerTierLabel: String? {
        switch snapshot.qualityTier {
        case "reliable": "靠谱答主"
        case "promising": "正在变靠谱"
        case "at_risk": "需要更认真"
        default: nil
        }
    }

    @MainActor
    private func loadSnapshot() async {
        guard !isLoading else { return }
        isLoading = true
        snapshot = await ProfileAPIService().fetchSnapshot()
        isLoading = false
    }
}

struct FavoritesScreen: View {
    let session: AppSession
    let onSelectHistory: (QuestionHistory) -> Void

    private var savedChoices: [QuestionHistory] {
        let historyChoices = session.history.filter { item in
            item.topPick != nil || item.status == "completed" || item.status == "top1"
        }
        let visibleHistoryChoices = historyChoices.filter { item in
            !session.hiddenFavoriteChoiceIds.contains(item.id)
        }
        return session.favoriteChoices + visibleHistoryChoices.filter { item in
            !session.favoriteChoices.contains(where: { $0.id == item.id })
        }
    }

    var body: some View {
        ProductListScreen(
            title: "收藏",
            subtitle: "保存过、采纳过和值得回看的选择。",
            systemImage: "bookmark",
            emptyTitle: "还没有收藏",
            emptyMessage: "推荐卡右上角的“…”里可以收藏。已经采纳的选择也会先放在这里。",
            isEmpty: savedChoices.isEmpty
        ) {
            if !savedChoices.isEmpty {
                ProductSection(title: "最近保存") {
                    VStack(spacing: 12) {
                        ForEach(savedChoices) { item in
                            FavoriteChoiceRow(
                                item: item,
                                onOpen: { onSelectHistory(item) },
                                onRemove: { session.removeFavoriteChoice(id: item.id) }
                            )
                        }
                    }
                }
            }
        }
    }
}

struct RewardsScreen: View {
    let session: AppSession
    let authRevision: Int

    @State private var snapshot = UserDashboardSnapshot.empty
    @State private var isLoading = false

    private var localPendingRewardItems: [RewardLedgerItem] {
        session.submittedAnswers
            .filter { $0.status == .pending }
            .map { answer in
                RewardLedgerItem(
                    id: answer.helpRequestId.uuidString,
                    title: answer.questionTitle,
                    subtitle: "等待对方采纳",
                    valueLabel: answer.rewardLabel,
                    status: .pending,
                    createdAt: answer.timeLabel
                )
            }
    }

    private var rewardItems: [RewardLedgerItem] {
        var seen = Set(snapshot.rewardItems.map(\.id))
        var items = snapshot.rewardItems
        for item in localPendingRewardItems where !seen.contains(item.id) {
            items.insert(item, at: 0)
            seen.insert(item.id)
        }
        return items
    }

    var body: some View {
        ProductListScreen(
            title: "奖励",
            subtitle: "待确认、已获得和未采用奖励都在这里。",
            systemImage: "gift",
            emptyTitle: "还没有奖励明细",
            emptyMessage: "帮别人来一句，被采纳后奖励会出现在这里。",
            isEmpty: false
        ) {
            ProductSection(title: "积分") {
                HStack(spacing: 10) {
                    ProfileMetricTile(value: "\(snapshot.grantedReward)", label: "已获得", secondary: nil)
                    ProfileMetricTile(
                        value: "\(snapshot.pendingReward + pendingLocalRewardValue)",
                        label: "待确认",
                        secondary: pendingLocalRewardValue > 0 ? "含刚提交" : nil
                    )
                    ProfileMetricTile(value: "\(snapshot.rejectedReward)", label: "未采用", secondary: nil)
                }
            }

            ProductSection(title: "明细") {
                if rewardItems.isEmpty {
                    ProductEmptyInline(
                        title: "还没有奖励明细",
                        message: "去来一句写一句，被采纳或待确认的奖励会归档到这里。"
                    )
                } else {
                    VStack(spacing: 12) {
                        ForEach(rewardItems) { item in
                            RewardLedgerRow(item: item)
                        }
                    }
                    .productPanel()
                }
            }

            ProductSection(title: "说明") {
                VStack(alignment: .leading, spacing: 12) {
                    RewardExplanationRow(icon: "clock", title: "待确认", subtitle: "对方还没采纳，先挂起。")
                    RewardExplanationRow(icon: "checkmark.seal", title: "已获得", subtitle: "你的来一句被采纳，奖励入账。")
                    RewardExplanationRow(icon: "minus.circle", title: "未采用", subtitle: "这次没被选中，不影响继续回答。")
                }
                .productPanel()
            }
        }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                ProductRefreshToolbarButton(isLoading: isLoading) {
                    Task { await loadSnapshot() }
                }
            }
        }
        .refreshable {
            await loadSnapshot()
        }
        .task(id: authRevision) {
            await loadSnapshot()
        }
    }

    private var pendingLocalRewardValue: Int {
        let snapshotIds = Set(snapshot.rewardItems.map(\.id))
        return localPendingRewardItems.filter { !snapshotIds.contains($0.id) }.reduce(0) { total, item in
            total + (Int(item.valueLabel.replacingOccurrences(of: "+", with: "")) ?? 0)
        }
    }

    @MainActor
    private func loadSnapshot() async {
        guard !isLoading else { return }
        isLoading = true
        snapshot = await ProfileAPIService().fetchSnapshot()
        isLoading = false
    }
}

struct MessagesScreen: View {
    let onMarkRead: ([UserLightEvent]) -> Void

    @State private var snapshot = UserDashboardSnapshot.empty
    @State private var isLoading = false

    var body: some View {
        ProductListScreen(
            title: "消息中心",
            subtitle: "有人回答、结果完成、奖励变动都会在这里提醒你。",
            systemImage: "bell",
            emptyTitle: "暂时没有新消息",
            emptyMessage: "有新的来一句、最终结果或奖励变化时，皮皮会放在这里。",
            isEmpty: snapshot.lightEvents.isEmpty
        ) {
            if !snapshot.lightEvents.isEmpty {
                ProductSection(title: "最新") {
                    VStack(spacing: 0) {
                        ForEach(Array(snapshot.lightEvents.enumerated()), id: \.element.id) { index, event in
                            ProfileMessageRow(event: event)

                            if index < snapshot.lightEvents.count - 1 {
                                Divider()
                                    .padding(.leading, 52)
                            }
                        }
                    }
                    .productPanel()
                }
            }
        }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                ProductRefreshToolbarButton(isLoading: isLoading) {
                    Task { await loadSnapshot() }
                }
            }
        }
        .refreshable {
            await loadSnapshot()
        }
        .task {
            await loadSnapshot()
        }
    }

    @MainActor
    private func loadSnapshot() async {
        guard !isLoading else { return }
        isLoading = true
        snapshot = await ProfileAPIService().fetchSnapshot()
        isLoading = false
        onMarkRead(snapshot.lightEvents)
    }
}

private struct ProductListScreen<Content: View>: View {
    let title: String
    let subtitle: String
    let systemImage: String
    let emptyTitle: String
    let emptyMessage: String
    let isEmpty: Bool
    @ViewBuilder let content: Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                ProductHeroHeader(title: title, subtitle: subtitle, systemImage: systemImage)

                content

                if isEmpty {
                    ProductEmptyState(title: emptyTitle, message: emptyMessage, systemImage: systemImage)
                }
            }
            .padding(.horizontal, 18)
            .padding(.top, 12)
            .padding(.bottom, 32)
        }
        .background(AppTheme.background.ignoresSafeArea())
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.large)
    }
}

private struct ProductHeroHeader: View {
    let title: String
    let subtitle: String
    let systemImage: String

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: systemImage)
                .font(.system(size: 22, weight: .semibold))
                .foregroundStyle(AppTheme.text)
                .frame(width: 48, height: 48)
                .background(AppTheme.bubble)
                .clipShape(Circle())

            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.system(size: 24, weight: .semibold))
                    .foregroundStyle(AppTheme.text)

                Text(subtitle)
                    .font(.system(size: 14))
                    .lineSpacing(4)
                    .foregroundStyle(AppTheme.textSecondary)
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .stroke(AppTheme.border, lineWidth: 1)
        )
    }
}

private struct ProductSection<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ProfileSectionHeader(title: title)
            content
        }
    }
}

private struct ProductEmptyState: View {
    let title: String
    let message: String
    let systemImage: String

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Image(systemName: systemImage)
                .font(.system(size: 24, weight: .semibold))
                .foregroundStyle(AppTheme.textMuted)

            Text(title)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(AppTheme.text)

            Text(message)
                .font(.system(size: 14))
                .lineSpacing(4)
                .foregroundStyle(AppTheme.textSecondary)
        }
        .productPanel()
    }
}

private struct ProductActionCard: View {
    let icon: String
    let title: String
    let subtitle: String

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: icon)
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(AppTheme.onPrimaryAction)
                .frame(width: 44, height: 44)
                .background(AppTheme.primaryAction)
                .clipShape(Circle())

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(AppTheme.text)
                Text(subtitle)
                    .font(.system(size: 13))
                    .lineSpacing(3)
                    .foregroundStyle(AppTheme.textSecondary)
            }

            Spacer()

            Image(systemName: "chevron.right")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(AppTheme.textMuted)
        }
        .padding(16)
        .background(AppTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .stroke(AppTheme.border, lineWidth: 1)
        )
    }
}

private struct FavoriteChoiceRow: View {
    let item: QuestionHistory
    let onOpen: () -> Void
    let onRemove: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 12) {
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: "bookmark.fill")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(AppTheme.text)
                        .frame(width: 34, height: 34)
                        .background(AppTheme.bubble)
                        .clipShape(Circle())

                    VStack(alignment: .leading, spacing: 5) {
                        Text(item.topPick?.title ?? item.query)
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(AppTheme.text)
                            .lineLimit(2)

                        Text(item.topPick?.reason ?? item.statusLabel)
                            .font(.system(size: 13))
                            .lineSpacing(3)
                            .foregroundStyle(AppTheme.textSecondary)
                            .lineLimit(2)
                    }
                }
                .contentShape(Rectangle())
                .onTapGesture(perform: onOpen)

                Spacer(minLength: 0)

                Button(action: onRemove) {
                    Image(systemName: "bookmark.slash")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(AppTheme.textSecondary)
                        .frame(width: 44, height: 44)
                        .background(AppTheme.bubble)
                        .clipShape(Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("取消收藏")
            }
        }
        .productPanel()
    }
}

private struct SubmittedAnswerRow: View {
    let answer: SubmittedAnswerRecord

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: "quote.bubble.fill")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(AppTheme.text)
                    .frame(width: 34, height: 34)
                    .background(AppTheme.bubble)
                    .clipShape(Circle())

                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 8) {
                        Text(answer.status.label)
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(AppTheme.green)
                            .padding(.horizontal, 9)
                            .padding(.vertical, 5)
                            .background(AppTheme.green.opacity(0.12))
                            .clipShape(Capsule())

                        Text(answer.rewardLabel)
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(AppTheme.textSecondary)

                        Spacer(minLength: 0)

                        Text(answer.timeLabel)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(AppTheme.textMuted)
                    }

                    Text(answer.questionTitle)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(AppTheme.text)
                        .lineLimit(2)

                    Text(answer.text)
                        .font(.system(size: 14))
                        .lineSpacing(4)
                        .foregroundStyle(AppTheme.textSecondary)
                        .lineLimit(3)
                }
            }
        }
        .productPanel()
    }
}

private struct HelpDetailSummaryPanel: View {
    let request: HelpRequest
    let isLoading: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .center, spacing: 10) {
                Text(request.status.label)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(AppTheme.text)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(AppTheme.bubble)
                    .clipShape(Capsule())

                Text(request.rewardLabel)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(AppTheme.green)

                Spacer(minLength: 0)

                if isLoading {
                    ProgressView()
                        .scaleEffect(0.72)
                        .tint(AppTheme.textMuted)
                } else {
                    Text("\(request.answerCount) 句")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(AppTheme.textMuted)
                }
            }

            Text(request.title)
                .font(.system(size: CardTextFitting.requestTitleSize(request.title, compact: true), weight: .semibold))
                .lineSpacing(3)
                .foregroundStyle(AppTheme.text)
                .lineLimit(3)
                .minimumScaleFactor(0.82)

            CollapsibleText(
                text: request.context,
                font: .system(size: 14),
                color: AppTheme.textSecondary,
                collapsedLineLimit: 3,
                lineSpacing: 4,
                expandThreshold: 92
            )

            HelpStructuredSummary(request: request, compact: true)
        }
        .productPanel()
    }
}

private struct HelpAnswerDetailRow: View {
    let answer: HumanAnswer

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "quote.bubble")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(AppTheme.text)
                .frame(width: 34, height: 34)
                .background(AppTheme.bubble)
                .clipShape(Circle())

            VStack(alignment: .leading, spacing: 8) {
                CollapsibleText(
                    text: answer.text,
                    font: .system(size: 15, weight: .medium),
                    color: AppTheme.text,
                    collapsedLineLimit: 4,
                    lineSpacing: 4,
                    expandThreshold: 96
                )

                Text("\(answer.nickname) · \(answer.timeLabel)")
                    .font(.system(size: 12))
                    .foregroundStyle(AppTheme.textMuted)
            }
        }
    }
}

private struct HelpFinalRecommendationPanel: View {
    let pick: TopPick

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                Image(systemName: "sparkles")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(AppTheme.green)
                    .frame(width: 34, height: 34)
                    .background(AppTheme.green.opacity(0.12))
                    .clipShape(Circle())

                VStack(alignment: .leading, spacing: 3) {
                    Text("皮皮帮你收口")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(AppTheme.textMuted)
                    Text(pick.title)
                        .font(.system(size: CardTextFitting.requestTitleSize(pick.title, compact: true), weight: .semibold))
                        .foregroundStyle(AppTheme.text)
                        .lineLimit(2)
                        .minimumScaleFactor(0.82)
                }
            }

            CollapsibleText(
                text: pick.reason.isEmpty ? pick.subtitle : pick.reason,
                font: .system(size: 14),
                color: AppTheme.textSecondary,
                collapsedLineLimit: 3,
                lineSpacing: 4,
                expandThreshold: 92
            )
        }
        .productPanel()
    }
}

private struct HelpFinalTextPanel: View {
    let answer: HumanAnswer

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("皮皮帮你收口")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(AppTheme.textMuted)

            CollapsibleText(
                text: answer.text,
                font: .system(size: 15, weight: .medium),
                color: AppTheme.text,
                collapsedLineLimit: 4,
                lineSpacing: 4,
                expandThreshold: 96
            )
        }
        .productPanel()
    }
}

private struct RewardLedgerRow: View {
    let item: RewardLedgerItem

    private var statusColor: Color {
        switch item.status {
        case .pending:
            AppTheme.orangeText
        case .granted:
            AppTheme.green
        case .rejected:
            AppTheme.textSecondary
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: item.status.icon)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(statusColor)
                .frame(width: 34, height: 34)
                .background(statusColor.opacity(0.12))
                .clipShape(Circle())

            VStack(alignment: .leading, spacing: 7) {
                HStack(spacing: 8) {
                    Text(item.status.label)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(statusColor)
                        .padding(.horizontal, 9)
                        .padding(.vertical, 5)
                        .background(statusColor.opacity(0.12))
                        .clipShape(Capsule())

                    Text(item.valueLabel)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(AppTheme.text)

                    Spacer(minLength: 0)

                    if let createdAt = item.createdAt, !createdAt.isEmpty {
                        Text(createdAt)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(AppTheme.textMuted)
                            .lineLimit(1)
                    }
                }

                Text(item.title)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(AppTheme.text)
                    .lineLimit(2)

                Text(item.subtitle)
                    .font(.system(size: 13))
                    .lineSpacing(3)
                    .foregroundStyle(AppTheme.textSecondary)
                    .lineLimit(2)
            }
        }
    }
}

private struct ProductEmptyInline: View {
    let title: String
    let message: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(AppTheme.text)
            Text(message)
                .font(.system(size: 13))
                .lineSpacing(3)
                .foregroundStyle(AppTheme.textSecondary)
        }
        .productPanel()
    }
}

private struct ProductRefreshToolbarButton: View {
    let isLoading: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                if isLoading {
                    ProgressView()
                        .scaleEffect(0.76)
                        .tint(AppTheme.text)
                } else {
                    Image(systemName: "arrow.clockwise")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(AppTheme.text)
                }
            }
            .frame(width: 44, height: 44)
            .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .disabled(isLoading)
        .accessibilityLabel(isLoading ? "正在刷新" : "刷新")
    }
}

private struct RewardExplanationRow: View {
    let icon: String
    let title: String
    let subtitle: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(AppTheme.textSecondary)
                .frame(width: 32, height: 32)
                .background(AppTheme.bubble)
                .clipShape(Circle())

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(AppTheme.text)
                Text(subtitle)
                    .font(.system(size: 13))
                    .foregroundStyle(AppTheme.textSecondary)
            }

            Spacer()
        }
    }
}

private extension View {
    func productPanel() -> some View {
        self
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(AppTheme.card)
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .stroke(AppTheme.border, lineWidth: 1)
            )
    }
}

private struct ProfileSectionHeader: View {
    let title: String

    var body: some View {
        Text(title)
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(AppTheme.textSecondary)
            .padding(.horizontal, 2)
    }
}

private struct ProfileMetricTile: View {
    let value: String
    let label: String
    let secondary: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(value)
                .font(.system(size: 23, weight: .semibold))
                .foregroundStyle(AppTheme.text)
                .lineLimit(1)
                .minimumScaleFactor(0.75)

            Text(label)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(AppTheme.textSecondary)

            if let secondary {
                Text(secondary)
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(AppTheme.green)
                    .lineLimit(1)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, minHeight: 98, alignment: .topLeading)
        .background(AppTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(AppTheme.border, lineWidth: 1)
        )
    }
}

private struct ProfileHistoryRow: View {
    let item: QuestionHistory

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 5) {
                Text(item.query)
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(AppTheme.text)
                    .lineLimit(1)

                Text(item.statusLabel)
                    .font(.system(size: 12))
                    .foregroundStyle(AppTheme.textSecondary)
            }

            Spacer()

            Image(systemName: "chevron.right")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(AppTheme.textMuted)
        }
        .padding(16)
        .contentShape(Rectangle())
    }
}

private struct ProfileMessageRow: View {
    let event: UserLightEvent

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "lightbulb.fill")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(AppTheme.green)
                .frame(width: 34, height: 34)
                .background(AppTheme.bubble)
                .clipShape(Circle())

            VStack(alignment: .leading, spacing: 4) {
                Text(event.title)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(AppTheme.text)
                Text(event.body)
                    .font(.system(size: 13))
                    .lineSpacing(3)
                    .foregroundStyle(AppTheme.textSecondary)
                    .lineLimit(3)
            }

            Spacer(minLength: 0)
        }
        .padding(16)
    }
}

private enum UIPolishPreviewFixtures {
    static let pickWithImage = TopPick(
        cardId: UUID(),
        query: "我在三里屯，想吃川菜",
        preface: "别查了，就这个。",
        title: "三里屯川菜，就选这家",
        subtitle: "三里屯 · 川菜",
        reason: "离你近，口味稳，适合现在直接做决定。",
        bullets: ["不应该显示"],
        warning: "不应该显示",
        followups: ["不应该显示"],
        referenceImage: ReferenceImage(
            url: "https://images.unsplash.com/photo-1555396273-367ea4eb4db5",
            sourceURL: "https://unsplash.com",
            sourceDomain: "unsplash.com",
            caption: "餐厅",
            isAiGenerated: false
        )
    )

    static let pickWithoutImage = TopPick(
        cardId: UUID(),
        query: "帮我找一下朝阳区热干面",
        preface: "别查了，就这个。",
        title: "朝阳区热干面，就选这家",
        subtitle: "朝阳区 · 热干面",
        reason: "你要的是热干面，先选距离和口味容错率都稳的一家。",
        bullets: ["不应该显示"],
        warning: "不应该显示",
        followups: ["不应该显示"],
        referenceImage: nil
    )

    static let helpDraft = HelpRequest(
        title: "韩国逛街不去明洞，求一个小众路线",
        context: "想逛街，避开游客区，最好顺路能买点小东西。",
        rewardLabel: "+10",
        answerCount: 0,
        status: .draft
    )

    static let helpAnswered = HelpRequest(
        title: "三里屯海底捞，两个人不太能吃辣怎么点",
        context: "人在店里，两个人，想稳一点，不要太辣也别浪费。",
        rewardLabel: "+8",
        answerCount: 2,
        status: .published
    )
}

private struct BottomComposerPreviewHost: View {
    @State private var text = ""

    var body: some View {
        VStack {
            Spacer()
            BottomComposer(text: $text, placeholder: "来一句，帮 TA 少纠结") {}
        }
        .appScreenBackground()
    }
}

#Preview("Input") {
    InputScreen(
        session: AppSession(service: MockCloudRecommendationService()),
        showsMessageBadge: true,
        onDecision: { _ in },
        onMenu: {},
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

#Preview("Recommendation Card · Image") {
    ChatRecommendationCard(
        pick: UIPolishPreviewFixtures.pickWithImage,
        isAccepting: false,
        onAskHuman: {},
        onAccept: {},
        onFavorite: {},
        onChange: {},
        onReportIssue: {},
        onShare: {}
    )
    .padding()
    .appScreenBackground()
}

#Preview("Recommendation Card · No Image") {
    ChatRecommendationCard(
        pick: UIPolishPreviewFixtures.pickWithoutImage,
        isAccepting: false,
        onAskHuman: {},
        onAccept: {},
        onFavorite: {},
        onChange: {},
        onReportIssue: {},
        onShare: {}
    )
    .padding()
    .appScreenBackground()
}

#Preview("Help Card · Draft") {
    ChatHelpCard(
        request: UIPolishPreviewFixtures.helpDraft,
        isPublishing: false,
        onPublish: {}
    )
    .padding()
    .appScreenBackground()
}

#Preview("Help Deck Card") {
    HelpDeckCard(request: UIPolishPreviewFixtures.helpAnswered)
        .frame(width: 370, height: 520)
        .padding()
        .appScreenBackground()
}

#Preview("Bottom Composer") {
    BottomComposerPreviewHost()
}
