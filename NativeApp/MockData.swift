import Foundation
import Observation

enum RecommendationDecision: Sendable {
    case top1(TopPick)
    case ask(HelpRequest)
}

struct RecommendationResult: Sendable {
    let sessionId: UUID?
    let questionId: UUID?
    let history: [QuestionHistory]
    let decision: RecommendationDecision
    let serviceNotice: ServiceNotice?
}

struct ServiceNotice: Equatable, Sendable {
    let title: String
    let detail: String
}

struct QuestionHistory: Identifiable, Hashable, Sendable {
    let id: UUID
    let query: String
    let status: String
    let helpRequestId: UUID?
    let topPick: TopPick?

    var statusLabel: String {
        switch status {
        case "completed":
            "已完成"
        case "top1":
            "已给选择"
        case "waiting_for_human":
            "等人来一句"
        case "answer_received":
            "已收到一句"
        default:
            "处理中"
        }
    }
}

enum HistoryDestination {
    case result
    case ask
}

struct TopPick: Hashable, Sendable {
    let cardId: UUID?
    let query: String
    let preface: String
    let title: String
    let subtitle: String
    let reason: String
    let bullets: [String]
    let warning: String
    let followups: [String]
    let referenceImage: ReferenceImage?
}

struct ReferenceImage: Hashable, Sendable {
    let url: String
    let sourceURL: String?
    let sourceDomain: String?
    let caption: String?
    let isAiGenerated: Bool
}

enum HelpRequestStatus: String, Codable, Hashable, Sendable {
    case draft
    case published
    case answered
    case completed

    var label: String {
        switch self {
        case .draft:
            "待发布"
        case .published:
            "已发布"
        case .answered:
            "已收到一句"
        case .completed:
            "已采纳"
        }
    }
}

struct HumanAnswer: Identifiable, Hashable, Sendable {
    let id: UUID
    let text: String
    let nickname: String
    let timeLabel: String

    init(id: UUID = UUID(), text: String, nickname: String, timeLabel: String) {
        self.id = id
        self.text = text
        self.nickname = nickname
        self.timeLabel = timeLabel
    }
}

struct HelpRequest: Identifiable, Hashable, Sendable {
    let id: UUID
    var title: String
    var context: String
    var status: HelpRequestStatus
    var answers: [HumanAnswer]

    init(
        id: UUID = UUID(),
        title: String,
        context: String,
        status: HelpRequestStatus = .draft,
        answers: [HumanAnswer] = []
    ) {
        self.id = id
        self.title = title
        self.context = context
        self.status = status
        self.answers = answers
    }
}

enum SubmitState: Equatable {
    case idle
    case loading
}

protocol RecommendationService: Sendable {
    func submit(query: String, sessionId: UUID?) async -> RecommendationResult
    func publish(_ request: HelpRequest, sessionId: UUID?, questionId: UUID?) async -> HelpRequest
    func refresh(_ request: HelpRequest) async -> HelpRequest
    func fetchHelpRequest(id: UUID) async -> HelpRequest?
    func answerQueue(excluding sessionId: UUID?) async -> [HelpRequest]
    func answer(_ text: String, for request: HelpRequest) async -> HelpRequest
    func acceptCard(id: UUID?) async -> Bool
    func complete(sessionId: UUID?, questionId: UUID?, helpRequestId: UUID?, source: String) async -> [QuestionHistory]
}

struct BackendRecommendationService: RecommendationService {
    private let baseURL = URL(string: "http://127.0.0.1:8788")!
    private let deviceUid = DeviceIdentity.uid

    func submit(query: String, sessionId: UUID?) async -> RecommendationResult {
        do {
            let conversationId = try await conversationId(existing: sessionId)
            let payload: V1ChatTurnResponse = try await perform(makeRequest(
                path: "/v1/chat/turn",
                method: "POST",
                body: V1ChatTurnRequest(
                    message: query,
                    conversationId: conversationId?.uuidString,
                    deviceId: deviceUid,
                    metadata: [:]
                )
            ))
            return payload.result(for: query)
        } catch {
            return RecommendationResult(
                sessionId: sessionId,
                questionId: nil,
                history: [],
                decision: MockData.backendUnavailableDecision(for: query),
                serviceNotice: MockData.backendUnavailableNotice
            )
        }
    }

    func publish(_ helpRequest: HelpRequest, sessionId: UUID?, questionId: UUID?) async -> HelpRequest {
        do {
            let response: V1ChatTurnResponse = try await perform(makeRequest(
                path: "/v1/chat/turn",
                method: "POST",
                body: V1ChatTurnRequest(
                    message: "发出去",
                    conversationId: sessionId?.uuidString,
                    deviceId: deviceUid,
                    metadata: ["help_card_id": helpRequest.id.uuidString]
                )
            ))
            return response.helpCards?.first?.model(fallbackTitle: helpRequest.title) ?? publishedFallback(helpRequest)
        } catch {
            return publishedFallback(helpRequest)
        }
    }

    func refresh(_ helpRequest: HelpRequest) async -> HelpRequest {
        guard helpRequest.status == .published else { return helpRequest }

        do {
            var components = URLComponents(url: endpoint("/v1/light-events"), resolvingAgainstBaseURL: false)!
            components.queryItems = [
                URLQueryItem(name: "device_id", value: deviceUid),
                URLQueryItem(name: "limit", value: "10")
            ]
            guard let url = components.url else { return helpRequest }
            let response: V1LightEventsResponse = try await perform(URLRequest(url: url))
            guard response.items.contains(where: { $0.helpCardId == helpRequest.id.uuidString }) else {
                return helpRequest
            }

            var refreshed = helpRequest
            refreshed.status = .answered
            refreshed.answers.append(HumanAnswer(text: "皮皮已经根据来一句汇总出结果。", nickname: "皮皮", timeLabel: "刚刚"))
            return refreshed
        } catch {
            return helpRequest
        }
    }

    func fetchHelpRequest(id: UUID) async -> HelpRequest? {
        nil
    }

    func answerQueue(excluding sessionId: UUID?) async -> [HelpRequest] {
        do {
            var components = URLComponents(url: endpoint("/v1/help-feed"), resolvingAgainstBaseURL: false)!
            let queryItems = [
                URLQueryItem(name: "device_id", value: deviceUid),
                URLQueryItem(name: "limit", value: "10")
            ]
            components.queryItems = queryItems

            guard let url = components.url else { return [] }
            let response: V1HelpFeedResponse = try await perform(URLRequest(url: url))
            return response.items.map { $0.model(fallbackTitle: "求一个") }
        } catch {
            return []
        }
    }

    func answer(_ text: String, for helpRequest: HelpRequest) async -> HelpRequest {
        do {
            let response: V1HelpCardOneLinerResponse = try await perform(makeRequest(
                path: "/v1/help-cards/\(helpRequest.id.uuidString)/one-liner",
                method: "POST",
                body: V1HelpCardOneLinerRequest(text: text, deviceId: deviceUid)
            ))
            var updated = helpRequest
            updated.answers.append(HumanAnswer(id: response.answerId ?? UUID(), text: text, nickname: "路过的人", timeLabel: "刚刚"))
            updated.status = response.isFinalReady ? .answered : .published
            return updated
        } catch {
            var fallback = helpRequest
            fallback.answers.append(HumanAnswer(text: text, nickname: "路过的人", timeLabel: "刚刚"))
            fallback.status = .answered
            return fallback
        }
    }

    func acceptCard(id: UUID?) async -> Bool {
        guard let id else { return false }

        do {
            let _: V1CardAcceptResponse = try await perform(makeRequest(
                path: "/v1/cards/\(id.uuidString)/accept",
                method: "POST",
                body: V1CardAcceptRequest(metadata: ["source": "ios"])
            ))
            return true
        } catch {
            return false
        }
    }

    func complete(sessionId: UUID?, questionId: UUID?, helpRequestId: UUID?, source: String) async -> [QuestionHistory] {
        []
    }

    private func makeRequest<Body: Encodable>(path: String, method: String, body: Body) throws -> URLRequest {
        var request = URLRequest(url: endpoint(path))
        request.httpMethod = method
        request.timeoutInterval = 18
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        return request
    }

    private func endpoint(_ path: String) -> URL {
        URL(string: path, relativeTo: baseURL)!.absoluteURL
    }

    private func perform<Response: Decodable>(_ request: URLRequest) async throws -> Response {
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse,
              (200..<300).contains(httpResponse.statusCode) else {
            throw URLError(.badServerResponse)
        }

        return try JSONDecoder().decode(Response.self, from: data)
    }

    private func conversationId(existing: UUID?) async throws -> UUID? {
        if let existing { return existing }

        let response: V1BootstrapResponse = try await perform(makeRequest(
            path: "/v1/bootstrap",
            method: "POST",
            body: V1BootstrapRequest(deviceId: deviceUid, platform: "ios", appVersion: "0.1.0")
        ))
        return UUID(uuidString: response.conversationId)
    }

    private func publishedFallback(_ helpRequest: HelpRequest) -> HelpRequest {
        var fallback = helpRequest
        fallback.status = .published
        return fallback
    }
}

private enum DeviceIdentity {
    static let uid: String = {
        let key = "just_pick_this_device_uid"
        if let existing = UserDefaults.standard.string(forKey: key), !existing.isEmpty {
            return existing
        }

        let generated = "ios-\(UUID().uuidString)"
        UserDefaults.standard.set(generated, forKey: key)
        return generated
    }()
}

private struct V1BootstrapRequest: Encodable {
    let deviceId: String
    let platform: String
    let appVersion: String

    enum CodingKeys: String, CodingKey {
        case deviceId = "device_id"
        case platform
        case appVersion = "app_version"
    }
}

private struct V1BootstrapResponse: Decodable {
    let conversationId: String

    enum CodingKeys: String, CodingKey {
        case conversationId = "conversation_id"
    }
}

private struct V1ChatTurnRequest: Encodable {
    let message: String
    let conversationId: String?
    let deviceId: String
    let metadata: [String: String]

    enum CodingKeys: String, CodingKey {
        case message
        case conversationId = "conversation_id"
        case deviceId = "device_id"
        case metadata
    }
}

private struct V1ChatTurnResponse: Decodable {
    let conversationId: String
    let userTurnId: String?
    let cards: [V1CardSummary]?
    let helpCards: [V1HelpCardSummary]?

    enum CodingKeys: String, CodingKey {
        case conversationId = "conversation_id"
        case userTurnId = "user_turn_id"
        case cards
        case helpCards = "help_cards"
    }

    func result(for query: String) -> RecommendationResult {
        let decision: RecommendationDecision
        if let card = cards?.first {
            decision = .top1(card.model(query: query))
        } else if let helpCard = helpCards?.first {
            decision = .ask(helpCard.model(fallbackTitle: query))
        } else {
            decision = .ask(MockData.backendFallbackHelpRequest(for: query))
        }

        return RecommendationResult(
            sessionId: UUID(uuidString: conversationId),
            questionId: questionId,
            history: [],
            decision: decision,
            serviceNotice: nil
        )
    }

    private var questionId: UUID? {
        if let questionId = cards?.first?.metadata?.questionId {
            return questionId
        }
        return helpCards?.first?.metadata?.questionId ?? UUID(uuidString: userTurnId ?? "")
    }
}

private struct V1CardSummary: Decodable {
    let id: UUID?
    let title: String
    let subtitle: String?
    let oneLiner: String?
    let bullets: [String]?
    let warning: String?
    let followups: [String]?
    let status: String?
    let image: V1ImageAsset?
    let metadata: V1CardMetadata?

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case subtitle
        case oneLiner = "one_liner"
        case bullets
        case warning
        case followups
        case status
        case image
        case metadata
    }

    func model(query fallbackQuery: String) -> TopPick {
        let resolvedReason = clean(oneLiner, fallback: "皮皮根据数据库信息直接给出一个选择。")
        let resolvedFollowups = removeAskHuman(
            from: cleanArray(followups, fallback: ["为什么选这个?", "有没有别的选择?"])
        )

        return TopPick(
            cardId: id,
            query: fallbackQuery,
            preface: "别查了,就这个。",
            title: clean(title, fallback: "先选一个最稳的"),
            subtitle: clean(subtitle, fallback: "不用再比较。"),
            reason: resolvedReason,
            bullets: cleanArray(bullets, fallback: [
                "皮皮已把数据库参考加工成当前这一问的选择。",
                "图片资产来自数据库 verified 非 AI 记录。",
                "只给一个低后悔选择。"
            ]),
            warning: clean(warning, fallback: "如果这个选择和你的偏好明显相反,就别选。"),
            followups: resolvedFollowups.isEmpty ? ["为什么选这个?", "有没有别的选择?"] : resolvedFollowups,
            referenceImage: image?.model
        )
    }
}

private struct V1CardMetadata: Decodable {
    let questionId: UUID?

    enum CodingKeys: String, CodingKey {
        case questionId = "question_id"
    }
}

private struct V1ImageAsset: Decodable {
    let id: UUID?
    let url: String?
    let sourceUrl: String?
    let sourceDomain: String?
    let caption: String?
    let verified: Bool
    let isAiGenerated: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case url
        case sourceUrl = "source_url"
        case sourceDomain = "source_domain"
        case caption
        case verified
        case isAiGenerated = "is_ai_generated"
    }

    var model: ReferenceImage? {
        guard let url, verified, !isAiGenerated else { return nil }
        return ReferenceImage(
            url: url,
            sourceURL: sourceUrl,
            sourceDomain: sourceDomain,
            caption: caption,
            isAiGenerated: isAiGenerated
        )
    }
}

private struct V1HelpCardSummary: Decodable {
    let id: UUID?
    let prompt: String
    let status: String?
    let oneLiner: String?
    let card: V1CardSummary?
    let metadata: V1HelpCardMetadata?

    enum CodingKeys: String, CodingKey {
        case id
        case prompt
        case status
        case oneLiner = "one_liner"
        case card
        case metadata
    }

    func model(fallbackTitle: String) -> HelpRequest {
        var answers: [HumanAnswer] = []
        if let card {
            answers.append(HumanAnswer(text: clean(card.oneLiner, fallback: card.title), nickname: "皮皮", timeLabel: "刚刚"))
        }

        return HelpRequest(
            id: id ?? UUID(),
            title: clean(prompt, fallback: fallbackTitle),
            context: clean(oneLiner, fallback: "这题不硬选 · 等懂的人来一句"),
            status: helpRequestStatus(from: status),
            answers: answers
        )
    }

    private func helpRequestStatus(from status: String?) -> HelpRequestStatus {
        switch status {
        case "draft":
            .draft
        case "published", "collecting", "open":
            .published
        case "final_ready", "answered":
            .answered
        case "closed", "completed":
            .completed
        default:
            .draft
        }
    }
}

private struct V1HelpCardMetadata: Decodable {
    let questionId: UUID?
    let answerCount: Int?
    let minAnswersRequired: Int?

    enum CodingKeys: String, CodingKey {
        case questionId = "question_id"
        case answerCount = "answer_count"
        case minAnswersRequired = "min_answers_required"
    }
}

private struct V1HelpFeedResponse: Decodable {
    let items: [V1HelpCardSummary]
}

private struct V1HelpCardOneLinerRequest: Encodable {
    let text: String
    let deviceId: String

    enum CodingKeys: String, CodingKey {
        case text
        case deviceId = "device_id"
    }
}

private struct V1HelpCardOneLinerResponse: Decodable {
    let helpCardId: String
    let answerId: UUID?
    let metadata: V1OneLinerMetadata?

    enum CodingKeys: String, CodingKey {
        case helpCardId = "help_card_id"
        case answerId = "answer_id"
        case metadata
    }

    var isFinalReady: Bool {
        metadata?.finalizationReady == true
    }
}

private struct V1OneLinerMetadata: Decodable {
    let finalizationReady: Bool?

    enum CodingKeys: String, CodingKey {
        case finalizationReady = "finalization_ready"
    }
}

private struct V1LightEventsResponse: Decodable {
    let items: [V1LightEvent]
}

private struct V1LightEvent: Decodable {
    let helpCardId: String?

    enum CodingKeys: String, CodingKey {
        case helpCardId = "help_card_id"
    }
}

private struct V1CardAcceptRequest: Encodable {
    let metadata: [String: String]
}

private struct V1CardAcceptResponse: Decodable {
    let cardId: String
    let accepted: Bool

    enum CodingKeys: String, CodingKey {
        case cardId = "card_id"
        case accepted
    }
}

struct MockCloudRecommendationService: RecommendationService {
    func submit(query: String, sessionId: UUID?) async -> RecommendationResult {
        try? await Task.sleep(for: .milliseconds(650))

        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        if shouldAskHuman(for: trimmed) {
            return RecommendationResult(
                sessionId: sessionId ?? UUID(),
                questionId: UUID(),
                history: [],
                decision: .ask(MockData.helpRequest(for: trimmed)),
                serviceNotice: nil
            )
        }

        return RecommendationResult(
            sessionId: sessionId ?? UUID(),
            questionId: UUID(),
            history: [],
            decision: .top1(MockData.topPick(for: trimmed)),
            serviceNotice: nil
        )
    }

    func publish(_ request: HelpRequest, sessionId: UUID?, questionId: UUID?) async -> HelpRequest {
        var updated = request
        updated.status = .published
        return updated
    }

    func refresh(_ request: HelpRequest) async -> HelpRequest {
        request
    }

    func fetchHelpRequest(id: UUID) async -> HelpRequest? {
        nil
    }

    func answerQueue(excluding sessionId: UUID?) async -> [HelpRequest] {
        [MockData.defaultHelpRequest]
    }

    func answer(_ text: String, for request: HelpRequest) async -> HelpRequest {
        var updated = request
        updated.answers.append(HumanAnswer(text: text, nickname: "路过的人", timeLabel: "刚刚"))
        updated.status = .answered
        return updated
    }

    func acceptCard(id: UUID?) async -> Bool {
        true
    }

    func complete(sessionId: UUID?, questionId: UUID?, helpRequestId: UUID?, source: String) async -> [QuestionHistory] {
        []
    }

    private func shouldAskHuman(for query: String) -> Bool {
        let uncertainKeywords = ["韩国", "首尔", "明洞", "小众", "求一个", "真人", "不敢", "失败", "没结果", "no result", "fail"]
        return uncertainKeywords.contains { keyword in
            query.localizedCaseInsensitiveContains(keyword)
        }
    }
}

private struct RecommendationRequest: Encodable {
    let query: String
    let sessionId: String?
}

private struct HelpRequestPayload: Encodable {
    let id: String
    let sessionId: String?
    let questionId: String?
    let title: String
    let context: String
    let status: HelpRequestStatus
    let answers: [HumanAnswerPayload]

    init(helpRequest: HelpRequest, status: HelpRequestStatus, sessionId: UUID?, questionId: UUID?) {
        self.id = helpRequest.id.uuidString
        self.sessionId = sessionId?.uuidString
        self.questionId = questionId?.uuidString
        self.title = helpRequest.title
        self.context = helpRequest.context
        self.status = status
        self.answers = helpRequest.answers.map(HumanAnswerPayload.init)
    }
}

private struct HumanAnswerPayload: Encodable {
    let id: String
    let text: String
    let nickname: String
    let timeLabel: String

    init(answer: HumanAnswer) {
        self.id = answer.id.uuidString
        self.text = answer.text
        self.nickname = answer.nickname
        self.timeLabel = answer.timeLabel
    }
}

private struct AnswerPayload: Encodable {
    let text: String
    let nickname: String
}

private struct CompleteQuestionPayload: Encodable {
    let helpRequestId: String?
    let source: String
}

private struct SessionEnvelope: Decodable {
    let session: SessionResponse
}

private struct SessionResponse: Decodable {
    let questions: [QuestionHistoryResponse]
}

private struct RecommendationResponse: Decodable {
    let sessionId: UUID?
    let questionId: UUID?
    let history: [QuestionHistoryResponse]?
    let kind: String
    let topPick: TopPickResponse?
    let helpRequest: HelpRequestResponse?

    func result(for query: String) -> RecommendationResult {
        let decision: RecommendationDecision
        switch kind {
        case "top1":
            guard let topPick else {
                decision = .ask(MockData.backendFallbackHelpRequest(for: query))
                break
            }
            decision = .top1(topPick.model(query: query))
        case "ask":
            guard let helpRequest else {
                decision = .ask(MockData.backendFallbackHelpRequest(for: query))
                break
            }
            decision = .ask(helpRequest.model(fallbackTitle: query))
        default:
            decision = .ask(MockData.backendFallbackHelpRequest(for: query))
        }

        return RecommendationResult(
            sessionId: sessionId,
            questionId: questionId,
            history: history?.compactMap(\.model) ?? [],
            decision: decision,
            serviceNotice: nil
        )
    }
}

private struct QuestionHistoryResponse: Decodable {
    let id: UUID?
    let query: String?
    let status: String?
    let helpRequestId: UUID?
    let topPick: TopPickResponse?

    var model: QuestionHistory? {
        guard let id, let query, let status else { return nil }
        return QuestionHistory(
            id: id,
            query: query,
            status: status,
            helpRequestId: helpRequestId,
            topPick: topPick?.model(query: query)
        )
    }
}

private struct HelpRequestEnvelope: Decodable {
    let helpRequest: HelpRequestResponse
}

private struct HelpRequestListEnvelope: Decodable {
    let helpRequests: [HelpRequestResponse]
}

private struct TopPickResponse: Decodable {
    let query: String?
    let preface: String?
    let title: String?
    let subtitle: String?
    let reason: String?
    let bullets: [String]?
    let warning: String?
    let followups: [String]?

    func model(query fallbackQuery: String) -> TopPick {
        let resolvedFollowups = removeAskHuman(
            from: cleanArray(followups, fallback: ["为什么?", "换个小众的"])
        )

        return TopPick(
            cardId: nil,
            query: clean(query, fallback: fallbackQuery),
            preface: clean(preface, fallback: "别查了,就这个。"),
            title: clean(title, fallback: "先选一个最稳的"),
            subtitle: clean(subtitle, fallback: "不用再比较。"),
            reason: clean(reason, fallback: "你已经给了位置和目的,这题先做一个低后悔选择。"),
            bullets: cleanArray(bullets, fallback: MockData.topPick(for: fallbackQuery).bullets),
            warning: clean(warning, fallback: "如果你明确不喜欢这个类型,就别选。"),
            followups: resolvedFollowups.isEmpty ? ["为什么?", "换个小众的"] : resolvedFollowups,
            referenceImage: nil
        )
    }
}

private struct HelpRequestResponse: Decodable {
    let id: UUID?
    let title: String?
    let context: String?
    let status: HelpRequestStatus?
    let answers: [HumanAnswerResponse]?

    func model(fallbackTitle: String) -> HelpRequest {
        HelpRequest(
            id: id ?? UUID(),
            title: clean(title, fallback: fallbackTitle),
            context: clean(context, fallback: "这题不硬选 · 等懂的人来一句"),
            status: status ?? .draft,
            answers: answers?.map(\.model) ?? []
        )
    }
}

private struct HumanAnswerResponse: Decodable {
    let id: UUID?
    let text: String?
    let nickname: String?
    let timeLabel: String?

    var model: HumanAnswer {
        HumanAnswer(
            id: id ?? UUID(),
            text: clean(text, fallback: ""),
            nickname: clean(nickname, fallback: "路过的人"),
            timeLabel: clean(timeLabel, fallback: "刚刚")
        )
    }
}

@MainActor
@Observable
final class AppSession {
    private(set) var sessionId: UUID?
    private(set) var currentQuestionId: UUID?
    private(set) var currentQuery = ""
    private(set) var currentTopPick: TopPick?
    private(set) var currentHelpRequest: HelpRequest?
    private(set) var history: [QuestionHistory] = []
    private(set) var answerQueue: [HelpRequest] = []
    private(set) var answerTarget: HelpRequest?
    private(set) var submitState: SubmitState = .idle
    private(set) var serviceNotice: ServiceNotice?

    @ObservationIgnored private let service: any RecommendationService
    @ObservationIgnored private let documentationDemo: String?

    init(service: any RecommendationService, documentationDemo: String? = nil) {
        self.service = service
        self.documentationDemo = documentationDemo

        #if DEBUG
        applyDocumentationDemo(documentationDemo)
        #endif
    }

    var isSubmitting: Bool {
        submitState == .loading
    }

    var topPick: TopPick {
        currentTopPick ?? MockData.topPick(for: currentQuery.isEmpty ? MockData.query : currentQuery)
    }

    var helpRequest: HelpRequest {
        currentHelpRequest ?? MockData.defaultHelpRequest
    }

    var answerRequest: HelpRequest? {
        answerTarget ?? answerQueue.first
    }

    func submit(query: String) async -> RecommendationDecision {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        currentQuery = trimmed
        submitState = .loading

        let result = await service.submit(query: trimmed, sessionId: sessionId)
        serviceNotice = result.serviceNotice
        sessionId = result.sessionId ?? sessionId
        currentQuestionId = result.questionId ?? currentQuestionId
        if !result.history.isEmpty {
            history = result.history
        } else {
            upsertLocalHistory(
                query: trimmed,
                status: status(for: result.decision),
                helpRequestId: helpRequestId(for: result.decision),
                topPick: topPick(for: result.decision)
            )
        }
        apply(result.decision)
        submitState = .idle
        return result.decision
    }

    func restoreHistoryItem(_ item: QuestionHistory) async -> HistoryDestination {
        currentQuestionId = item.id
        currentQuery = item.query

        if shouldOpenHelpRequest(for: item) {
            currentTopPick = nil
            if let helpRequestId = item.helpRequestId,
               let request = await service.fetchHelpRequest(id: helpRequestId) {
                currentHelpRequest = request
            } else {
                currentHelpRequest = fallbackHelpRequest(for: item)
            }
            return .ask
        }

        currentHelpRequest = nil
        currentTopPick = item.topPick ?? MockData.topPick(for: item.query)
        return .result
    }

    func makeHelpRequestFromCurrentTopPick() {
        let query = currentQuery.isEmpty ? MockData.query : currentQuery
        let pick = topPick
        currentHelpRequest = HelpRequest(
            title: query,
            context: "已经给过一个选择: \(pick.title) · 还想听懂的人来一句",
            status: .draft,
            answers: []
        )
    }

    func addHelpContext(_ text: String) {
        let supplement = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !supplement.isEmpty else { return }

        ensureHelpRequest()
        currentHelpRequest?.context += "\n补充: \(supplement)"
    }

    func publishCurrentRequest() async {
        ensureHelpRequest()
        guard let request = currentHelpRequest else { return }
        let published = await service.publish(request, sessionId: sessionId, questionId: currentQuestionId)
        currentHelpRequest = published
        upsertLocalHistory(query: published.title, status: "waiting_for_human", helpRequestId: published.id, topPick: currentTopPick)
    }

    func refreshCurrentHelpRequest() async -> Bool {
        guard let request = currentHelpRequest else { return false }
        let previousAnswerCount = request.answers.count
        let refreshed = await service.refresh(request)
        currentHelpRequest = refreshed
        if refreshed.answers.count > previousAnswerCount {
            upsertLocalHistory(query: refreshed.title, status: "answer_received", helpRequestId: refreshed.id, topPick: currentTopPick)
            return true
        }
        return false
    }

    func loadAnswerQueue() async {
        #if DEBUG
        if documentationDemo == "answer", !answerQueue.isEmpty {
            answerTarget = answerQueue.first
            return
        }
        #endif

        let requests = await service.answerQueue(excluding: sessionId)
        answerQueue = requests
        answerTarget = requests.first
    }

    func addAnswer(_ text: String) async {
        let answer = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !answer.isEmpty else { return }

        guard let request = answerRequest else { return }
        let updated = await service.answer(answer, for: request)

        answerTarget = updated
        if currentHelpRequest?.id == updated.id {
            currentHelpRequest = updated
        }
        answerQueue.removeAll { $0.id == updated.id }
    }

    func acceptCurrentTopPick() async {
        let accepted = await service.acceptCard(id: currentTopPick?.cardId)
        let remoteHistory: [QuestionHistory]
        if accepted {
            remoteHistory = []
        } else {
            remoteHistory = await service.complete(
                sessionId: sessionId,
                questionId: currentQuestionId,
                helpRequestId: nil,
                source: "top1"
            )
        }
        markCurrentQuestionCompleted(remoteHistory: remoteHistory)
        currentTopPick = nil
        currentQuery = ""
    }

    func acceptCurrentHelpAnswer() async {
        let remoteHistory = await service.complete(
            sessionId: sessionId,
            questionId: currentQuestionId,
            helpRequestId: currentHelpRequest?.id,
            source: "human_answer"
        )
        markCurrentQuestionCompleted(remoteHistory: remoteHistory)
        currentHelpRequest = nil
        currentQuery = ""
    }

    private func apply(_ decision: RecommendationDecision) {
        switch decision {
        case .top1(let pick):
            currentTopPick = pick
        case .ask(let request):
            currentTopPick = nil
            currentHelpRequest = request
        }
    }

    private func ensureHelpRequest() {
        guard currentHelpRequest == nil else { return }
        currentHelpRequest = MockData.helpRequest(for: currentQuery.isEmpty ? MockData.query : currentQuery)
    }

    private func upsertLocalHistory(query: String, status: String, helpRequestId: UUID?, topPick: TopPick?) {
        if let currentQuestionId,
           let index = history.firstIndex(where: { $0.id == currentQuestionId }) {
            let existing = history[index]
            history[index] = QuestionHistory(
                id: currentQuestionId,
                query: query,
                status: status,
                helpRequestId: helpRequestId,
                topPick: topPick ?? existing.topPick
            )
            return
        }

        let id = currentQuestionId ?? UUID()
        currentQuestionId = id
        history.insert(
            QuestionHistory(
                id: id,
                query: query,
                status: status,
                helpRequestId: helpRequestId,
                topPick: topPick
            ),
            at: 0
        )
    }

    private func status(for decision: RecommendationDecision) -> String {
        switch decision {
        case .top1:
            "top1"
        case .ask:
            "waiting_for_human"
        }
    }

    private func helpRequestId(for decision: RecommendationDecision) -> UUID? {
        switch decision {
        case .top1:
            nil
        case .ask(let request):
            request.id
        }
    }

    private func topPick(for decision: RecommendationDecision) -> TopPick? {
        switch decision {
        case .top1(let pick):
            pick
        case .ask:
            nil
        }
    }

    private func shouldOpenHelpRequest(for item: QuestionHistory) -> Bool {
        if item.helpRequestId != nil {
            return true
        }

        return item.status == "waiting_for_human" || item.status == "answer_received"
    }

    private func fallbackHelpRequest(for item: QuestionHistory) -> HelpRequest {
        HelpRequest(
            id: item.helpRequestId ?? UUID(),
            title: item.query,
            context: item.status == "completed"
                ? "这题已经完成。"
                : "这题不硬选 · 等懂的人来一句",
            status: helpRequestStatus(for: item),
            answers: []
        )
    }

    private func helpRequestStatus(for item: QuestionHistory) -> HelpRequestStatus {
        switch item.status {
        case "completed":
            .completed
        case "answer_received":
            .answered
        case "waiting_for_human":
            .published
        default:
            .draft
        }
    }

    private func markCurrentQuestionCompleted(remoteHistory: [QuestionHistory]) {
        if !remoteHistory.isEmpty {
            history = remoteHistory
            return
        }

        let query = currentQuery.isEmpty ? MockData.query : currentQuery
        upsertLocalHistory(query: query, status: "completed", helpRequestId: currentHelpRequest?.id, topPick: currentTopPick)
    }

    #if DEBUG
    private func applyDocumentationDemo(_ demo: String?) {
        guard let demo else { return }

        switch demo {
        case "result":
            currentQuery = MockData.query
            currentTopPick = MockData.topPick(for: MockData.query)
        case "ask":
            currentQuery = "在韩国逛街，不想去明洞"
            currentHelpRequest = HelpRequest(
                title: "在韩国逛街，不想去明洞",
                context: "用户说：在韩国逛街，不想去明洞。先收集懂的人一句建议。",
                status: .draft,
                answers: []
            )
        case "answer":
            let request = HelpRequest(
                title: "在韩国逛街，不想去明洞",
                context: "用户说：在韩国逛街，不想去明洞，想小众，求一个。",
                status: .published,
                answers: []
            )
            answerQueue = [request]
            answerTarget = request
        default:
            break
        }
    }
    #endif
}

enum MockData {
    static let query = "我现在在大同喜晋道,不知道吃什么"
    static let backendUnavailableNotice = ServiceNotice(
        title: "本地兜底",
        detail: "后端未连接，先用本地规则给你一个选择。"
    )

    static let defaultHelpRequest = HelpRequest(
        title: "韩国逛街,不去明洞,想小众",
        context: "女生 · 小众品牌 · 美妆 · 不去游客区"
    )

    static func topPick(for query: String) -> TopPick {
        let resolvedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? Self.query : query

        return TopPick(
            cardId: nil,
            query: resolvedQuery,
            preface: "别查了,就这个。",
            title: "刀削面 + 肉丸子",
            subtitle: "第一次来大同,就吃这个最稳。",
            reason: "你已经给了位置和目的,这题不需要再比较菜单。先吃一个地方感强、点偏概率低的组合。",
            bullets: [
                "你已经到店了,别再研究菜单。",
                "第一次来大同,要吃一个地方感强、不容易点偏的。",
                "这组比只点面更完整。"
            ],
            warning: "不爱吃面,就别选。",
            followups: ["为什么?", "换个小众的"],
            referenceImage: nil
        )
    }

    static func helpRequest(for query: String) -> HelpRequest {
        let resolvedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? defaultHelpRequest.title : query

        if resolvedQuery.localizedCaseInsensitiveContains("韩国")
            || resolvedQuery.localizedCaseInsensitiveContains("首尔")
            || resolvedQuery.localizedCaseInsensitiveContains("明洞") {
            return defaultHelpRequest
        }

        return HelpRequest(
            title: resolvedQuery,
            context: "这题不硬选 · 等懂的人来一句"
        )
    }

    static func backendFallbackHelpRequest(for query: String) -> HelpRequest {
        let resolvedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? defaultHelpRequest.title : query

        return HelpRequest(
            title: resolvedQuery,
            context: "云测暂时没给出一个足够稳的选择 · 发出去等懂的人来一句"
        )
    }

    static func backendUnavailableDecision(for query: String) -> RecommendationDecision {
        let resolvedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        if resolvedQuery.localizedCaseInsensitiveContains("大同")
            || resolvedQuery.localizedCaseInsensitiveContains("喜晋道") {
            return .top1(topPick(for: resolvedQuery))
        }

        return .ask(backendFallbackHelpRequest(for: resolvedQuery))
    }
}

private func clean(_ value: String?, fallback: String) -> String {
    guard let value else { return fallback }
    let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
    return trimmed.isEmpty ? fallback : trimmed
}

private func cleanArray(_ value: [String]?, fallback: [String]) -> [String] {
    guard let value else { return fallback }
    let cleaned = value
        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        .filter { !$0.isEmpty }
    return cleaned.isEmpty ? fallback : cleaned
}

private func removeAskHuman(from values: [String]) -> [String] {
    values.filter { !$0.localizedCaseInsensitiveContains("问真人") }
}
